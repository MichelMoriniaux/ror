# Complete project details at https://RandomNerdTutorials.com

try:
  import usocket as socket
except:
  import socket

from machine import Pin
import network
import time

# import esp
# esp.osdebug(None)

import gc
gc.collect()

ssid = 'Short-Circuit-Dome'
password = 'SCDomeNet'

station = network.WLAN(network.STA_IF)

station.active(True)
station.connect(ssid, password)

while station.isconnected() == False:
  pass

print('Connection successful')
print(station.ifconfig())

# ESP32 GPIO 26
open = Pin(32, Pin.IN)
open.init(pull=Pin.PULL_DOWN,value=0)
closed = Pin(33, Pin.IN)
closed.init(pull=Pin.PULL_DOWN,value=0)
button = Pin(25)
button.init(pull=Pin.PULL_DOWN,value=0)
action = Pin(27, Pin.OUT)
action.off()
lidar_switch = Pin(26, Pin.OUT)
lidar_switch.off()
