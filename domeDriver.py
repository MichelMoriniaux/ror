# domeDriver: Simple Alpaca Roll Off Roof device

import webrepl
import uasyncio
from machine import Pin
from machine import PWM
from machine import ADC
from machine import UART
#import wlancred_home as wlancred   # contains WLAN SSID and password
import wlancred
import myconfig
import time
from ld06 import processpacket, packetcrc
from mipyalpaca.alpacaserver import AlpacaServer
from mipyalpaca.alpacadome import DomeDevice
from microdot_utemplate import render_template


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
        self.safe = False  # is the roof safe to move, modified by lidar. prevent any movement if False
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
                    if sw["name"] == "Open":
                        self.open = i
                        self.openstate = self.switchValue[i]
                    if sw["name"] == "Button":
                        self.button = i
                        self.buttonstate = self.switchValue[i]
            else:
                self.swpin.insert(i, "UserDef")
        # we now need to figure out the state of the shutter and if unknown
        if self.swpin[self.open].value() == self.swpin[self.closed].value() == 1:
            # shutter should never be in this state 
            print("=====>Error, both endstops triggered")
            self.ShutterStatus = myconfig.ERROR
        elif self.swpin[self.open].value() == self.swpin[self.closed].value():
            # Shutter is in undertermined state in between the endstops
            print("=====>Shutter in unknown state")
        elif self.swpin[self.open].value() == 1:
            print("=====>Shutter is OPEN")
            self.ShutterStatus = myconfig.OPENED
            self.next_button_state = myconfig.CLOSE
        elif self.swpin[self.closed].value() == 1:
            print("=====>Shutter is CLOSED")
            self.ShutterStatus = myconfig.CLOSED
            self.next_button_state = myconfig.OPEN

    def _open_triggered(self, new_value):
        # Trigger has happened, determine if the switch was activated or
        # de-activated
        # activated first
        print("=====>Open Triggered")
        if new_value == 1:
            print("======>Roof is Open")
            # Shutter is now open
            self.ShutterStatus = myconfig.OPENED
            self.next_button_state = myconfig.CLOSE
            self.Slewing = False
        else:  # new_value == 0:
            # Shutter is closing
            print("======>Roof is Closing")
            self.ShutterStatus = myconfig.CLOSING
            self.next_button_state = myconfig.STOP_CLOSE
            self.Slewing = True
        self.openstate = new_value

    def _closed_triggered(self, new_value):
        # Trigger has happened, determine if the switch was activated or
        # de-activated
        # activated first
        print("=====>Closed Triggered")
        if new_value == 1:
            # shutter is now closed
            print("======>Roof is Closed")
            self.ShutterStatus = myconfig.CLOSED
            self.next_button_state = myconfig.OPEN
            self.Slewing = False
        else:  # new_value == 0:
            # Shutter is opening
            print("======>Roof is Opening")
            self.ShutterStatus = myconfig.OPENING
            self.next_button_state = myconfig.STOP_OPEN
            self.Slewing = True
        self.closedstate = new_value

    def _button_pressed(self):
        # the manual button has been pressed
        # we need to uptade our state and abort the movement if the roof is not safe
        print("=====>button pressed")
        # This might be an emergency stop so check that first
        if self.Slewing:
            print("=====>button pressed to STOP")
            self.abortslew()
        else:
            # we have commanded movement, this will only be allowed if safe
            if self.check_safe():
                self._pulse_button()
                self.Slewing = True
                if self.next_button_state == myconfig.STOP_CLOSE:
                    # the button was pressed to close the roof
                    self.ShutterStatus = myconfig.CLOSING
                if self.next_button_state == myconfig.STOP_OPEN:
                    # the button was pressed to open the roof
                    self.ShutterStatus = myconfig.OPENING

    def _pulse_button(self):
        print("=====>Pulse Button ON")
        self.swpin[self.action].on()
        time.sleep_ms(500)
        print("=====>Pulse Button OFF")
        self.swpin[self.action].off()
        self.next_button_state += 1
        if self.next_button_state > 3:
            self.next_button_state = 0

    def check_safe(self):
        print("=====>checking safety with LIDAR")
        self.set_safe(True)
        # turn on the LIDAR
        if self.swpin[self.lidar].value() != 1:
            self.swpin[self.lidar].on()
        # sleep for a second to let the lidar time to warm up
        time.sleep_ms(1000)
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < 1000:
            char = self.ser.read(1)
            if char == b'\x54':  # Packet Header
                char = self.ser.read(1)
                if char == b'\x2c':  # Packet Version
                    packet = self.ser.read(45)
                    try:
                        data, crc = processpacket(packet)
                        if crc != packetcrc(b'\x54' + b'\x2c' + packet):
                            print("======> CRC mismatch")
                        for reading in data:
                            if reading[1] > 500:
                                if reading[0] >= myconfig.ANGLES[0] or reading[0] <= myconfig.ANGLES[1]:
                                    # print(reading)
                                    if reading[1] < myconfig.SAFE_DISTANCE:
                                        print(reading)
                                        print("=====> UNSAFE")
                                        # self.set_safe(False)
                    except:
                        print("=====>Error reading packet")
        # turn off the LIDAR
        if not self.Slewing:
            self.swpin[self.lidar].off()
        return self.get_safe()

    def lidar_on(self):
        self.swpin[self.lidar].on()

    def lidar_off(self):
        self.swpin[self.lidar].off()

    def update_switch_states(self):
        new_button_state = self.swpin[self.button].value()
        if self.buttonstate != new_button_state and new_button_state == 1: # button has been pressed (TODO check for npn or pnp)
            self.buttonstate = new_button_state
            self._button_pressed()
        elif self.buttonstate != new_button_state and new_button_state == 0: # button has been released
            self.buttonstate = new_button_state
        new_open_state = self.swpin[self.open].value()
        new_closed_state = self.swpin[self.closed].value()
        # both cannot be triggered at the same time
        if new_closed_state == new_open_state == 1:
            self.ShutterStatus = myconfig.ERROR
            return
        if self.openstate != new_open_state:  # open has triggered
            self._open_triggered(new_open_state)
        if self.closedstate != new_closed_state:  # close has triggered
            self._closed_triggered(new_closed_state)

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
        if self.check_safe():
            print("=====>closing Shutter")
            super().closeshutter()
            if self.ShutterStatus == myconfig.OPENED:
                self._pulse_button()
                self.Slewing = True
                self.ShutterStatus = myconfig.CLOSING
        else:
            print("=====>Roof not safe, aborting close")

    def openshutter(self):
        if self.check_safe():
            print("=====>opening Shutter")
            super().openshutter()
            if self.ShutterStatus == myconfig.CLOSED:
                self._pulse_button()
                self.Slewing = True
                self.ShutterStatus = myconfig.OPENING
        else:
            print("=====>Roof not safe, aborting open")

    def GET_azimuth(self, request):
        raise NotImplementedError()

    def GET_altitude(self, request):
        raise NotImplementedError()

    # return setup page
    def setupRequest(self, request):
        return render_template('setupswitch0.html', devname=self.name,
                               cfgfile=self.configfile)


async def get_data():
    global roof

    while True:
        if roof.Slewing:
           if not roof.check_safe():
               roof.abortslew()
        # Process roof end switches
        roof.update_switch_states()
        # wait 1 second before the next update
        # print(f'roof {roof.ShutterStatus} OeS: {roof.openstate} CeS: {roof.closedstate}')
        await uasyncio.sleep_ms(100)


# Asyncio coroutine
async def main():
    uasyncio.create_task(webrepl.start())
    uasyncio.create_task(get_data())
    await AlpacaServer.startServer()


# Create Alpaca Server
srv = AlpacaServer("MyPicoServer", "MMX", "0.01", "Unknown")
AlpacaServer.connectStationMode(wlancred.ssid, wlancred.password)

roof = MiPyRoRDevice(0, "ESP32 RollOffRoof",
                     "0d5cfb76-51ad-464f-841e-6451e6ba0f44",
                     "dome_config.json")

# Install dome device
srv.installDevice("dome", 0, roof)

# Connect to WLAN

# run main function via asyncio
uasyncio.run(main())
