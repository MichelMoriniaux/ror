# Complete project details at https://RandomNerdTutorials.com

web_page = """<html><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>
  body{font-family:Arial; text-align: center; margin: 0px auto; padding-top:30px;}
  .switch{position:relative;display:inline-block;width:120px;height:68px}.switch input{display:none}
  .slider{position:absolute;top:0;left:0;right:0;bottom:0;background-color:#ccc;border-radius:34px}
  .slider:before{position:absolute;content:"";height:52px;width:52px;left:8px;bottom:8px;background-color:#fff;-webkit-transition:.4s;transition:.4s;border-radius:68px}
  input:checked+.slider{background-color:#2196F3}
  input:checked+.slider:before{-webkit-transform:translateX(52px);-ms-transform:translateX(52px);transform:translateX(52px)}
  </style><script>function pressButton() { var xhr = new XMLHttpRequest(); xhr.open("GET", "/?action=on", true); xhr.send(); }</script></head><body>
  <h1>ESP Roof Web Server</h1><label class="switch"><input type="button" value="roof" onclick="pressButton()"><span class="slider">
  </span></label></body></html>"""

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(('', 80))
s.listen(5)

while True:
  try:
    if gc.mem_free() < 102000:
      gc.collect()
    conn, addr = s.accept()
    conn.settimeout(3.0)
    print('Got a connection from %s' % str(addr))
    request = conn.recv(1024)
    conn.settimeout(None)
    request = str(request)
    print('Content = %s' % request)
    relay_on = request.find('/?action=on')
    if relay_on == 6:
      print('Web button pressed')
      action.on()
      time.sleep(250)
      action.off()
    conn.send('HTTP/1.1 200 OK\n')
    conn.send('Content-Type: text/html\n')
    conn.send('Connection: close\n\n')
    conn.sendall(web_page)
    conn.close()
  except OSError as e:
    conn.close()
    print('Connection closed')
