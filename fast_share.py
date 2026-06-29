import asyncio
import http.server
import socketserver
import threading
import mss
import cv2  # Requires: pip install opencv-python
import numpy as np

# Combined HTML & JavaScript using WebSocket for instant frame rendering
HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>High-FPS Python Screen Share</title>
    <style>
        body { margin: 0; background: #000; display: flex; justify-content: center; align-items: center; height: 100vh; overflow: hidden; font-family: sans-serif;}
        img { max-width: 100%; max-height: 100%; object-fit: contain; }
        #fps { position: absolute; top: 10px; left: 10px; color: #0f0; background: rgba(0,0,0,0.7); padding: 5px 10px; border-radius: 4px; }
    </style>
</head>
<body>
    <div id="fps">FPS: 0</div>
    <img id="screen" src="" alt="Waiting for stream...">
    <script>
        const img = document.getElementById('screen');
        const fpsCounter = document.getElementById('fps');
        let frameCount = 0;
        
        setInterval(() => {
            fpsCounter.innerText = `FPS: ${frameCount}`;
            frameCount = 0;
        }, 1000);

        const ws = new WebSocket(`ws://${window.location.hostname}:8002`);
        ws.binaryType = 'blob';

        ws.onmessage = (event) => {
            const url = URL.createObjectURL(event.data);
            const oldUrl = img.src;
            img.src = url;
            frameCount++;
            if (oldUrl) URL.revokeObjectURL(oldUrl);
        };

        ws.onerror = (err) => console.error("Stream error: ", err);
    </script>
</body>
</html>
"""

import websockets

current_frame = b""
frame_lock = threading.Lock()

def capture_loop():
    """Background loop dedicated entirely to hyper-fast screen capture and JPEG compression."""
    global current_frame
    with mss.MSS() as sct:
        monitor = sct.monitors[1]
        
        # Optimize compression quality (80 is a good sweet spot for speed vs quality)
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
        
        while True:
            # 1. Grab raw pixels from screen (blazing fast)
            sct_img = sct.grab(monitor)
            
            # 2. Convert to numpy array directly without extra copy operations
            img_np = np.frombuffer(sct_img.bgra, dtype=np.uint8).reshape(sct_img.height, sct_img.width, 4)
            
            # 3. Convert to BGR (OpenCV format)
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
            
            # 4. Compress to JPEG (Significantly faster than PNG)
            result, img_bytes = cv2.imencode('.jpg', img_bgr, encode_param)
            
            if result:
                with frame_lock:
                    current_frame = img_bytes.tobytes()

async def stream_handler(websocket):
    """Pushes the newest captured frame down the WebSocket pipeline."""
    global current_frame
    last_sent = b""
    try:
        while True:
            with frame_lock:
                frame_to_send = current_frame
            
            # Only send if the frame has changed and isn't empty
            if frame_to_send and frame_to_send != last_sent:
                await websocket.send(frame_to_send)
                last_sent = frame_to_send
            
            # Yield control back to the event loop immediately 
            await asyncio.sleep(0.001) 
    except websockets.exceptions.ConnectionClosed:
        pass

class HTTPHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode("utf-8"))

def start_http_server():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", 8000), HTTPHandler) as httpd:
        httpd.serve_forever()

async def main():
    threading.Thread(target=capture_loop, daemon=True).start()
    threading.Thread(target=start_http_server, daemon=True).start()
    
    print("High-performance streaming engine initialized.")
    print("Open http://localhost:8000 to view your screen.")
    
    async with websockets.serve(stream_handler, "0.0.0.0", 8002):
        await asyncio.get_running_loop().create_future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStreaming halted.")
