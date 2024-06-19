import struct

# Packet Structure
# All packets start with 0x54 for the first byte, have a static version of 0x2c for the second byte, then the following structure:
#packet = b'\x0b\x0e\xc8\x45\x33\x02\xea\x43\x02\xec\x24\x02\xec\xa8\x01\xe4\xa1\x01\xee\x9e\x01\xee\xa3\x01\xee\xa5\x01\xee\xa0\x01\xef\xa4\x01\xed\xa6\x01\xee\xa7\x01\xee\x04\x49\x37\x6b\xc0'
#           speed  ,startan,distanc,int,distanc,int,distanc,int,distanc,int,distanc,int,distanc,int,distanc,int,distanc,int,distanc,int,distanc,int,distanc,int,distanc,int,endangl,timesta,crc

# speed:  35.95, 0e 0b
# startangle:  178.64, 45 c8
# endangle:  186.92, 49 04
# timestamp:  27447, 6b 37
# crc:  192, c0
#
# --------Data: 3 bytes per reading, 12 readings
# Distance: 563, 02 33
# Confidence: ea
# Angle: 178.6
# Distance: 579, 02 43
# Confidence: ec
# Angle: 179.3
# 

def processpacket(packet):
    ## Some things are commented out for efficiency. Uncomment if you need them.
    ## Packet Header
    #speed = struct.unpack('<H', packet[0:2])[0] #Bytes 0 and 1, little endian, degrees per second
    startangle = struct.unpack('<H', packet[2:4])[0] / 100 #Bytes 2 and 3, little endian, convert to float

    ## Packet Footer
    endangle = struct.unpack('<H', packet[40:42])[0] / 100 #Bytes 40 and 41, little endian, convert to float
    #timestamp = struct.unpack('<H', packet[42:44])[0] #Bytes 42 and 43
    crc = struct.unpack('<B', packet[44:45])[0] #Byte 44

    #print("Speed:", speed, "Start Angle:", startangle, "End Angle:", endangle, "TimeStamp:", timestamp, "CRC:", crc)

    ## Packet Data
    if(endangle - startangle > 0):
        angleStep = float(endangle - startangle)/(12)
    else:
        angleStep = float((endangle + 360) - startangle)/(12)

    angleStep %= 360 # Normalize angleStep to 0-360

    data = []
    counter = 0
    num_readings = 12 # 12 readings per packet
    bytes_per_reading = 3 # 3 bytes per reading: 2 for distance, 1 for confidence
    sample_ratio = 1 # 1 = process every reading, 2 = process every other packet, etc.

    for i in range(0, num_readings * bytes_per_reading, 3 * sample_ratio):
        angle = round((angleStep * i/3 + startangle) % 360, 1) # Angle of the reading, Degrees
        distance = struct.unpack('<H', packet[4+i:6+i])[0] # First 2 bytes of the data structure, little endian, distance in mm
        confidence = struct.unpack('<B', packet[6+i:7+i])[0] # Last byte of the data structure, confidence of returned light, 0-255
        counter += 1
        
        data.append([angle, distance, confidence])

    return data, crc

def packetcrc(packet):
    crc_table = b'\x00\x4d\x9a\xd7\x79\x34\xe3\xae\xf2\xbf\x68\x25\x8b\xc6\x11\x5c\xa9\xe4\x33\x7e\xd0\x9d\x4a\x07\x5b\x16\xc1\x8c\x22\x6f\xb8\xf5\x1f\x52\x85\xc8\x66\x2b\xfc\xb1\xed\xa0\x77\x3a\x94\xd9\x0e\x43\xb6\xfb\x2c\x61\xcf\x82\x55\x18\x44\x09\xde\x93\x3d\x70\xa7\xea\x3e\x73\xa4\xe9\x47\x0a\xdd\x90\xcc\x81\x56\x1b\xb5\xf8\x2f\x62\x97\xda\x0d\x40\xee\xa3\x74\x39\x65\x28\xff\xb2\x1c\x51\x86\xcb\x21\x6c\xbb\xf6\x58\x15\xc2\x8f\xd3\x9e\x49\x04\xaa\xe7\x30\x7d\x88\xc5\x12\x5f\xf1\xbc\x6b\x26\x7a\x37\xe0\xad\x03\x4e\x99\xd4\x7c\x31\xe6\xab\x05\x48\x9f\xd2\x8e\xc3\x14\x59\xf7\xba\x6d\x20\xd5\x98\x4f\x02\xac\xe1\x36\x7b\x27\x6a\xbd\xf0\x5e\x13\xc4\x89\x63\x2e\xf9\xb4\x1a\x57\x80\xcd\x91\xdc\x0b\x46\xe8\xa5\x72\x3f\xca\x87\x50\x1d\xb3\xfe\x29\x64\x38\x75\xa2\xef\x41\x0c\xdb\x96\x42\x0f\xd8\x95\x3b\x76\xa1\xec\xb0\xfd\x2a\x67\xc9\x84\x53\x1e\xeb\xa6\x71\x3c\x92\xdf\x08\x45\x19\x54\x83\xce\x60\x2d\xfa\xb7\x5d\x10\xc7\x8a\x24\x69\xbe\xf3\xaf\xe2\x35\x78\xd6\x9b\x4c\x01\xf4\xb9\x6e\x23\x8d\xc0\x17\x5a\x06\x4b\x9c\xd1\x7f\x32\xe5\xa8'
    crc = 0
    for byte in packet:
        crc = crc_table[(crc ^ byte) & 0xff]

    return crc
