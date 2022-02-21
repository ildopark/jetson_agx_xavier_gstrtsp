import os
import cv2
import numpy as np
import gi
import time
import threading
from enum import Enum
from sys import stdout

gi.require_version('Gst', '1.0')
gi.require_version('GstRtspServer', '1.0')
from gi.repository import Gst, GstRtspServer, GObject

image_change = [0, 0, 0, 0]
thread_kill = 0

#image capture thread (4Ch)
class Worker(threading.Thread):
    def __init__(self, index):
        super().__init__()
        self._kill = threading.Event()
        self.index = index
    def run(self):
        print('start thread : ', self.index)
        prevtime = time.time()
        SAMPLE_COUNT = 10
        cycle = [0 for i in range(SAMPLE_COUNT)]
        indexCycle = 0
        fps = 0
        while 1:
            global captue, latestImage
            ret, image = capture[self.index].read()
            if ret:
                #print('convert : ', self.index)
                cycle[indexCycle] = round((time.time() - prevtime) * 1000)
                indexCycle += 1
                if indexCycle >= SAMPLE_COUNT:
                    indexCycle = 0
                    sum = 0
                    for i in range(SAMPLE_COUNT):
                        sum += cycle[i]
                    avg = sum / SAMPLE_COUNT
                    fps = round(1000 / avg, 1)
                h, w, c = image.shape
                cv2.putText(image,"CH" + str(self.index+1), (int(w/128), int(h/20 * 19)), cv2.FONT_HERSHEY_PLAIN, int(w/250), (255,255,255), int(w/170))
                latestImage[self.index] = image
                image_change[self.index] = 1
                prevtime = time.time()
            if thread_kill == 1:
                capture[self.index].release()
                break

    def kill(self):
        self._kill.set()
        
def createEmptyImage(height, width, channel):
    image = np.zeros((height, width, channel), np.uint8)
    return image
    
def merge4Image(raw):
    img = raw[:]#deep copy
    height, width, channel = img[0].shape
    cheight = (int)(height/2)
    cwidth = (int)(width/2)
    image = createEmptyImage(height, width, channel)
    for i in range(4):
        img[i] = cv2.resize(img[i], dsize=(cwidth, cheight), interpolation=cv2.INTER_LINEAR)
        axisHeight = (int)(i / 2)
        axisWidth = (int)(i % 2)
        image[axisHeight * cheight:(axisHeight + 1) * cheight, axisWidth * cwidth:(axisWidth + 1) * cwidth] = img[i][0:cheight, 0:cwidth]
    h, w, c = image.shape
    cv2.putText(image,"Resolution " + RES_NAME, (int(w/256), int(h/20)), cv2.FONT_HERSHEY_PLAIN, int(w/430), (255,255,255), int(w/300))
    return image

def captureImage(index):
    ret, frame = capture[index].read()
    return frame

class SensorFactory(GstRtspServer.RTSPMediaFactory):
    def __init__(self, **properties):
        super(SensorFactory, self).__init__(**properties)
        self.set_latency(0)
        self.number_frames = 0
        self.fps = FRAME
        self.prevtime = time.time()
        self.duration = 1 / self.fps * 1000  # duration of a frame in milliseconds
        self.launch_string = 'appsrc name=source is-live=true block=true format=GST_FORMAT_TIME ' \
                             'caps=video/x-raw,format=BGR,width={},height={},framerate={}/1 ' \
                             '! videoconvert ! video/x-raw,format=I420 ' \
                             '! omxh264enc control-rate=disable ' \
                             '! rtph264pay config-interval=1 name=pay0 pt=96'.format(WIDTH[RES_INDEX], HEIGHT[RES_INDEX], self.fps,)

#omxh264enc doc : typing $ gst-inspect-1.0 omxh264enc


    def on_need_data(self, src, length):
        image_projection = 0
        for i in range(4):
            if image_change[i] == 1:
                image_projection += 1
            else:
                image_projection = 0
                break;
        if image_projection == 4:
            image_projection = 0
            frame = merge4Image(latestImage)
            data = frame.tostring()
            buf = Gst.Buffer.new_allocate(None, len(data), None)
            buf.fill(0, data)
            buf.duration = self.duration
            timestamp = self.number_frames * self.duration
            buf.pts = buf.dts = int(timestamp)
            buf.offset = timestamp
            self.number_frames += 1
            retval = src.emit('push-buffer', buf)
            ter_col, ter_row = os.get_terminal_size()
            playtime = time.time() - self.prevtime
            if thread_kill != 1:
                stdout.write("Resolution %s, Frame rate %3.1f, pushed Frames %6d, palytime %6.2fs\n" %(RES_NAME, round(self.number_frames/playtime, 1), self.number_frames, playtime))
            
            #self.prevtime = time.time()
            if retval != Gst.FlowReturn.OK:
                print(retval)

    def do_create_element(self, url):
        return Gst.parse_launch(self.launch_string)
    
    def do_configure(self, rtsp_media):
        self.prevtime = time.time()
        self.number_frames = 0
        appsrc = rtsp_media.get_element().get_child_by_name('source')
        appsrc.connect('need-data', self.on_need_data)


class GstServer(GstRtspServer.RTSPServer):
    def __init__(self, **properties):
        super(GstServer, self).__init__(**properties)
        self.factory = SensorFactory()
        self.factory.set_shared(True)
        self.get_mount_points().add_factory("/test", self.factory)
        self.attach(None)

#main
Resolution = { 'nHD':0, 'qHD':1, 'HD':2, 'HD_PLUS':3, 'FHD':4 }
RES_NAME = 'HD'
RES_INDEX = Resolution[RES_NAME]
FRAME = 60
WIDTH = [640, 960, 1280, 1600, 1920]
HEIGHT = [360, 540, 720, 900, 1080]

while 1:
    input_res = input('Resolution\nnHD : 640 X 360\nqHD : 960 X 840\nHD : 1280 X 720\nHD_PLUS : 1600 X 900\nFHD : 1920 X 1080\n : ')
    if input_res in Resolution:
        RES_NAME = input_res
        RES_INDEX = Resolution[RES_NAME]
        print("selected resolution is {}({}X{})".format(input_res, WIDTH[RES_INDEX], HEIGHT[RES_INDEX]))
        time.sleep(1)
        print("")
        break
    else:
        print("Wrong input.\n")
        time.sleep(1)
capture = [ cv2.VideoCapture("nvarguscamerasrc sensor-id=0 ! video/x-raw(memory:NVMM), width=(int)" + str(WIDTH[RES_INDEX]) + ", height=(int)" + str(HEIGHT[RES_INDEX]) + ", format=(string)NV12, framerate=(fraction)"+ str(FRAME) + "/1 ! nvvidconv flip-method=2 ! nvvidconv ! video/x-raw, format=(string)BGRx ! videoconvert !  appsink"), \
            cv2.VideoCapture("nvarguscamerasrc sensor-id=1 ! video/x-raw(memory:NVMM), width=(int)" + str(WIDTH[RES_INDEX]) + ", height=(int)" + str(HEIGHT[RES_INDEX]) + ", format=(string)NV12, framerate=(fraction)"+ str(FRAME) + "/1 ! nvvidconv flip-method=2 ! nvvidconv ! video/x-raw, format=(string)BGRx ! videoconvert !  appsink"), \
            cv2.VideoCapture("nvarguscamerasrc sensor-id=2 ! video/x-raw(memory:NVMM), width=(int)" + str(WIDTH[RES_INDEX]) + ", height=(int)" + str(HEIGHT[RES_INDEX]) + ", format=(string)NV12, framerate=(fraction)"+ str(FRAME) + "/1 ! nvvidconv flip-method=2 ! nvvidconv ! video/x-raw, format=(string)BGRx ! videoconvert !  appsink"), \
            cv2.VideoCapture("nvarguscamerasrc sensor-id=3 ! video/x-raw(memory:NVMM), width=(int)" + str(WIDTH[RES_INDEX]) + ", height=(int)" + str(HEIGHT[RES_INDEX]) + ", format=(string)NV12, framerate=(fraction)"+ str(FRAME) + "/1 ! nvvidconv flip-method=2 ! nvvidconv ! video/x-raw, format=(string)BGRx ! videoconvert !  appsink") ]
index = 0
latestImage = [captureImage(0), captureImage(1), captureImage(2), captureImage(3)]
t = [None] * 4
for i in range(4):
    t[i] = Worker(i)
    t[i].start()
    
GObject.threads_init()
Gst.init(None)

server = GstServer()
loop = GObject.MainLoop()

try:
    loop.run()
    
finally:
    thread_kill = 1
    pass