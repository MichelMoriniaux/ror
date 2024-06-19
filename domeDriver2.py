# domeDriver: Simple Alpaca Roll Off Roof device

import uasyncio
from machine import Pin
from machine import UART
import wlancred_home as wlancred   # contains WLAN SSID and password
# import wlancred
import myconfig
import time
from ld06 import processpacket, packetcrc
from mipyalpaca.alpacaserver import AlpacaServer
from mipyalpaca.alpacadome import DomeDevice
from microdot_utemplate import render_template
import gc

DEBUG = False

class MiPyRoRDevice(DomeDevice):

    def __init__(self, devnr, devname, uniqueid, config_file):
        super().__init__(devnr, devname, uniqueid, config_file)
        self.CanFindHome = False
        self.CanPark = False
        self.CanSetAltitude = False
        self.CanSetAzimuth = False
        self.CanSetPark = False
        self.CanSlave = False
        self.CanSyncAzimuth = False
        self.CanSetShutter = True
        self.AtHome = False
        self.AtPark = False
        # driver vars
        self.description = "MicroPython Alpaca dome device"
        self.swpin = []
        self.dome_value = []
        # state of the next button push 0:open, 1:stop, 2:close, 3:stop
        self.next_button_state = myconfig.OPEN
        self.closed = 0  # pin index of the closed enstop switch
        self.open = 0  # pin index of the open enstop switch
        self.button = 0 # pin index of the button sensor
        self.action = 0  # pin index of the action relay
        self.lidar = 0 # pin to turn on the lidar
        self.closedstate = 0  # state of the closed endstop
        self.openstate = 0  # state of open endstop
        self.buttonstate = 0 # state of the button
        self.safe = True  # is the roof safe to move, modified by lidar. prevent any movement if False
        self.pressed = False  # has the button been pressed?
        self.pressed_time = 0
        self.Azimuth = 0
        self.ser = UART(1, baudrate=230400, tx=17, rx=16)

        # configure all MicroPython pins
        for i in range(self.maxswitch):
            sw = self.domedescr[i]

            if sw["swfct"] == "MiPyPin":
                cfg = sw["pincfg"]
                pnr = int(cfg["pin"])

                if cfg["pinfct"] == "OUTP":
                    # output pin
                    p = Pin(pnr, Pin.OUT)
                    if cfg["initval"] is not None:
                        # set initial value
                        self.switchValue[i] = int(cfg["initval"])
                        p.init(value=int(cfg["initval"]))
                        p.value(int(cfg["initval"]))
                    self.swpin.insert(i, p)
                    if sw["name"] == "Action":
                        self.action = i
                    if sw["name"] == "LIDAR":
                        self.lidar = i
                if cfg["pinfct"] == "INP":
                    # input pin
                    p = Pin(pnr, Pin.IN)
                    # setup pullup
                    if cfg["pull"] == "PULL_UP":
                        p.init(pull=Pin.PULL_UP)
                    if cfg["pull"] == "PULL_DOWN":
                        p.init(pull=Pin.PULL_DOWN)
                    self.switchValue[i] = int(p.value())
                    self.swpin.insert(i, p)
                    if sw["name"] == "Closed":
                        self.closed = i
                        self.closedstate = self.switchValue[i]
                        debug(f"Closed: {self.closedstate}")
                    if sw["name"] == "Open":
                        self.open = i
                        self.openstate = self.switchValue[i]
                        debug(f"Open: {self.openstate}")
                    if sw["name"] == "Button":
                        self.button = i
                        self.buttonstate = self.switchValue[i]
                        debug(f"Button: {self.buttonstate}")
            else:
                self.swpin.insert(i, "UserDef")
        # we now need to figure out the state of the shutter and if unknown
        if self.swpin[self.open].value() == self.swpin[self.closed].value() == 1:
            # shutter should never be in this state 
            debug("=>Error, both endstops triggered")
            self.ShutterStatus = myconfig.ERROR
        elif self.swpin[self.open].value() == self.swpin[self.closed].value():
            # Shutter is in undertermined state in between the endstops
            debug("=>Shutter in unknown state")
        elif self.swpin[self.open].value() == 1:
            debug("=>Shutter is OPEN")
            self.ShutterStatus = myconfig.OPENED
            self.next_button_state = myconfig.CLOSE
        elif self.swpin[self.closed].value() == 1:
            debug("=>Shutter is CLOSED")
            self.ShutterStatus = myconfig.CLOSED
            self.next_button_state = myconfig.OPEN

    def _open_triggered(self, new_value):
        # Trigger has happened, determine if the switch was activated or
        # de-activated
        # activated first
        debug("==>Open Triggered")
        if new_value == 1:
            debug("===>Roof is Open")
            # Shutter is now open
            self.ShutterStatus = myconfig.OPENED
            self.next_button_state = myconfig.CLOSE
            self.Slewing = False
        else:  # new_value == 0:
            # Shutter is closing
            debug("===>Roof is Closing")
            self.ShutterStatus = myconfig.CLOSING
            self.next_button_state = myconfig.STOP_CLOSE
            self.Slewing = True
        self.openstate = new_value

    def _closed_triggered(self, new_value):
        # Trigger has happened, determine if the switch was activated or
        # de-activated
        # activated first
        debug("==>Closed Triggered")
        if new_value == 1:
            # shutter is now closed
            debug("===>Roof is Closed")
            self.ShutterStatus = myconfig.CLOSED
            self.next_button_state = myconfig.OPEN
            self.Slewing = False
        else:  # new_value == 0:
            # Shutter is opening
            debug("===>Roof is Opening")
            self.ShutterStatus = myconfig.OPENING
            self.next_button_state = myconfig.STOP_OPEN
            self.Slewing = True
        self.closedstate = new_value

    def _button_pressed(self):
        # the manual button has been pressed
        # we need to uptade our state and abort the movement if the roof is not safe
        debug("==>_button_pressed: button pressed")
        # This might be an emergency stop so check that first
        if self.Slewing:
            debug("===>_button_pressed: button pressed to STOP")
            self.abortslew()
        else:
            self.press()

    def _pulse_button(self):
        debug("====>_pulse_button: Pulse Button ON")
        self.swpin[self.action].on()
        time.sleep_ms(250)
        debug("====>_pulse_button: Pulse Button OFF")
        self.swpin[self.action].off()
        self.next_button_state += 1
        if self.next_button_state > 3:
            self.next_button_state = 0

    def press(self):
        debug("===>press: pressed")
        self.pressed = True
        self.pressed_time = time.time()

    async def button_detector(self):
        while True:
            # debug("==>button_detector")
            delta = time.time() - self.pressed_time
            if self.pressed and delta > 5:
                debug("===>button_detector: pressed good to check")
                # enough time has elapsed to get reliable lidar readings
                if self.safe:
                    debug("====>button_detector: safe")
                    self._pulse_button()
                    self.Slewing = True
                    if self.next_button_state == myconfig.STOP_CLOSE:
                        # the button was pressed to close the roof
                        self.ShutterStatus = myconfig.CLOSING
                    if self.next_button_state == myconfig.STOP_OPEN:
                        # the button was pressed to open the roof
                        self.ShutterStatus = myconfig.OPENING
                else:
                    debug("====>button_detector: NOT safe")
                    self.ShutterStatus = myconfig.ERROR
                self.pressed = False
            await uasyncio.sleep_ms(100)

    async def check_safe(self):
        # Coroutine to read from a lidar
        # when slewing or the button has been pressed activate the lidar and read it
        # as read() is blocking and the lidar does 10RPM this will be mostly idle
        # when not moving wait 100ms between runs
        while True:
            # debug("==>check_safe")
            if self.Slewing or self.pressed:
                # debug("===>slewing or pressed")
                # turn on the LIDAR
                if self.swpin[self.lidar].value() != 1:
                    debug("===>check_safe: turn lidar on")
                    self.lidar_on()
                    await uasyncio.sleep_ms(200)
                # read lidar data
                char = self.ser.read(1)  #mblocking call should use stream handler
                if char == b'\x54':  # Packet Header
                    char = self.ser.read(1)
                    if char == b'\x2c':  # Packet Version
                        packet = self.ser.read(45)
                        debug("====>check_safe: read full packet")
                        try:
                            data, crc = processpacket(packet)
                            calccrc = packetcrc(b'\x54' + b'\x2c' + packet[:-1])
                            if crc == calccrc:
                                for reading in data:
                                    if reading[0] >= myconfig.ANGLES[0] or reading[0] <= myconfig.ANGLES[1]:
                                        if reading[1] < myconfig.SAFE_DISTANCE and reading[1] > 500:
                                            debug(reading)
                                            print("=>check_safe: UNSAFE")
                                            self.safe = False
                                            if self.Slewing:
                                                self.abortslew()
                            else:
                                debug(f"======>check_safe: CRC mismatch: {crc} / {calccrc}")
                        except:
                            debug("=====>check_safe: Error reading packet")
                            pass
                await uasyncio.sleep_ms(0)
            else:
                # turn off the LIDAR
                if self.swpin[self.lidar].value() != 0:
                    debug("===>check_safe: turn lidar off")
                    self.lidar_off()
                self.safe = True
                await uasyncio.sleep_ms(100)

    def lidar_on(self):
        self.swpin[self.lidar].on()

    def lidar_off(self):
        self.swpin[self.lidar].off()

    async def update_switch_states(self):
        while True:
            # debug("==>upd_sw_st")
            new_button_state = self.swpin[self.button].value()
            if self.buttonstate != new_button_state and new_button_state == 0: # button has been pressed
                self.buttonstate = new_button_state
                self._button_pressed()
            elif self.buttonstate != new_button_state and new_button_state == 1: # button has been released
                self.buttonstate = new_button_state
            new_open_state = self.swpin[self.open].value()
            new_closed_state = self.swpin[self.closed].value()
            # both cannot be triggered at the same time
            if new_closed_state == new_open_state == 1:
                self.ShutterStatus = myconfig.ERROR
            elif self.openstate != new_open_state:  # open has triggered
                self._open_triggered(new_open_state)
            elif self.closedstate != new_closed_state:  # close has triggered
                self._closed_triggered(new_closed_state)
            await uasyncio.sleep_ms(100)

    def get_open_endstop(self):
        return self.openstate

    def get_closed_endstop(self):
        return self.closedstate

    def get_safe(self):
        return self.safe

    def set_safe(self, safety):
        self.safe = safety
 
    def abortslew(self):
        if self.Slewing:
            self._pulse_button()
        super().abortslew()

    def closeshutter(self):
        debug("==>closing Shutter Requested")
        super().closeshutter()
        if self.ShutterStatus == myconfig.OPENED:
            self.ShutterStatus = myconfig.CLOSING
            self.press()

    def openshutter(self):
        debug("==>opening Shutter Requested")
        super().openshutter()
        if self.ShutterStatus == myconfig.CLOSED:
            self.ShutterStatus = myconfig.OPENING
            self.press()

    # return setup page
    def setupRequest(self, request):
        return render_template('setupswitch0.html', devname=self.name,
                               cfgfile=self.configfile)

def debug(text):
    if DEBUG:
        print(text)

async def main():
    debug("=> start update_switch_states")
    uasyncio.create_task(roof.update_switch_states())
    debug("=> start button_detector")
    uasyncio.create_task(roof.button_detector())
    debug("=> start check_safe")
    uasyncio.create_task(roof.check_safe())
    debug("=> start alpaca server")
    await AlpacaServer.startServer()


# Create Alpaca Server
# micropython.mem_info()
srv = AlpacaServer("MyPicoServer", "MMX", "0.01", "Unknown")
# micropython.mem_info()
# Connect to WLAN
gc.collect()
# micropython.mem_info()
AlpacaServer.connectStationMode(wlancred.ssid, wlancred.password)
# micropython.mem_info()
roof = MiPyRoRDevice(0, "ESP32 RollOffRoof",
                     "0d5cfb76-51ad-464f-841e-6451e6ba0f44",
                     "dome_config.json")
# micropython.mem_info()
# Install dome device
srv.installDevice("dome", 0, roof)
# micropython.mem_info()
# run main function via asyncio
try:
    uasyncio.run(main())
finally:
    uasyncio.new_event_loop()