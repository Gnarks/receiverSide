
import numpy as np
from gnuradio import gr
from sigmf import SigMFFile
from sigmf.utils import get_data_type_str, get_sigmf_iso8601_datetime_now
import time
import socket
import os

class SyncFileSaver(gr.sync_block):
    """
    docstring for block SyncFileSaver
    """
    def __init__(self, 
                sample_rate=64000,
                 distance=5,
                 indoor=True,
                 save_directory="~/Music/testSave/",
                 scenario_name="poc",
                 port=12345,
                 ip_address="127.0.0.1",
                 other_info="",
                 ):
        gr.sync_block.__init__(self,
            name="Syncronised File Saver",
            in_sig=[np.complex64],
            out_sig=None)

        # first, establish the TCP connection with the transmitter

        self.connected = False
        self.port = port
        self.ip_address = ip_address


        # set the current cycle at 0
        self.current_cycle = 0

        # root directory to save the scenario directory to 
        self.save_directory = save_directory
        # name of directory to save the devices directories (where all the capture files belong)
        self.scenario_name = scenario_name

        # scenario context 
        self.sample_rate = sample_rate
        self.description = f"capture at {distance}m {"indoor" if indoor else "outdoor"}. {other_info}"


    def work(self, input_items, output_items):
        data = input_items[0]


        if self.connected == False:

            print(f"Waiting for transmitter to connect to PORT:{self.port}")
            # by IP with TCP 
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind((self.ip_address, self.port))

            sock.listen(5)
            self.conn, addr = sock.accept()
            print("Connected established with transmitter")


            # transmission parameters
            self.frequency = self.get_next_var_from_sock(self.conn) * 1e6
            print(f"frequency received: {self.frequency}")

            self.sf = self.get_next_var_from_sock(self.conn)
            print(f"sf received: {self.sf}")

            self.bw = self.get_next_var_from_sock(self.conn) * 1e3
            print(f"bw received: {self.bw}")


            # device list to keep track of the origin of the signal
            self.device_list = self.get_next_var_from_sock(self.conn)
            print(f"device list received: {self.device_list}")
           
            # set the first device to be listened to 
            self.current_device, self.current_index = self.device_list[0], 0

            # time synchronisation parameters 
            self.start_time = self.get_next_var_from_sock(self.conn)
            print(f"start_time received: {self.start_time} compared to current {time.perf_counter()}")
            
            self.period = self.get_next_var_from_sock(self.conn)  # should be given in s
            print(f"period received: {self.period}")

            # next time to save the file
            self.next = self.start_time + self.period

            self.cycles = self.get_next_var_from_sock(self.conn)
            print(f"cycles received: {self.cycles}")
            self.connected = True
            self.conn.close()

        # wait for the start time
        if time.perf_counter() < self.start_time:
            return 0
        # stop if all captured
        if self.current_cycle >= self.cycles:
            return 0
        
        # wait for the period to save the file
        finished = self.save_frame_during_period(input_items)

        # move the current index and device
        if finished:
            self.next_device()

        return 0

    def save_frame_during_period(self, data):
        """ waiting until the next period """
        if time.perf_counter() < self.next:
            self.save_frame(data)
            return False

        print(f"stopped saving at {time.perf_counter()} compared to {self.next} \n drift : {time.perf_counter() - self.next}")
        self.next += self.period

        # create the metadata
        meta = SigMFFile(
        data_file=f"{self.save_directory}/{self.scenario_name}/device{self.current_device}/cycle_{self.current_cycle}.sigmf-data", # extension is optional
        global_info = {
            SigMFFile.DATATYPE_KEY: "cf32_le",  
            SigMFFile.FREQUENCY_KEY: self.frequency,
            SigMFFile.SAMPLE_RATE_KEY: self.sample_rate,
            SigMFFile.DESCRIPTION_KEY: self.description,
        })

        meta.add_capture(self.current_cycle, metadata={
            SigMFFile.DATETIME_KEY: get_sigmf_iso8601_datetime_now(),
        })

        # save the meta file
        meta.tofile(f"{self.save_directory}/{self.scenario_name}/device{self.current_device}/cycle_{self.current_cycle}.sigmf-meta") # extension is optional

        print(f"{self.current_device} : [{self.current_cycle}/{self.cycles}] saved")

        return True



    def save_frame(self, input_items):

        data = input_items[0]
        # create the data file and saves it
        filename = f"{self.save_directory}/{self.scenario_name}/device{self.current_device}/cycle_{self.current_cycle}.sigmf-data"
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, "ab") as f:
            np.array(data).tofile(f)
        self.consume(0, len(data))


    def next_device(self):

        # change device
        print(f"moved from {self.current_device} ", end="")
        changeCycle = self.current_index+1 == len(self.device_list)
        self.current_index = (self.current_index +1) % len(self.device_list)
        self.current_device = self.device_list[self.current_index]

        print(f"to {self.current_device}")
        # if the last device in the list
        if changeCycle:
            self.current_cycle += 1
            print(f"next cycle :{self.current_cycle}")

        print()
        if self.current_cycle == self.cycles:
            print("all cycles are done !")

    def get_next_var_from_sock(self, sock):

        sep = '\n'
        data = sock.recv(1).decode("utf-8")
        buf = data
        # if deconnected
        if data == '':
            raise Exception("tried to read a variable but empty socket buffer")

        # while not seen the separator
        while sep not in buf and data:
            buf += sock.recv(1).decode("utf-8")

        if buf != '':
            data = eval(buf)
            return data
            
            

