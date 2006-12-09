"""This library implements the tftp protocol, based on rfc 1350.
http://www.faqs.org/rfcs/rfc1350.html
At the moment it implements only a client class, but will include a server,
with support for variable block sizes.
"""

import struct, socket, logging, time, sys, types

# Make sure that this is at least Python 2.4
verlist = sys.version_info
if not verlist[0] >= 2 or not verlist[1] >= 4:
    raise AssertionError, "Requires at least Python 2.4"

LOG_LEVEL = logging.NOTSET
MIN_BLKSIZE = 8
DEF_BLKSIZE = 512
MAX_BLKSIZE = 65536
SOCK_TIMEOUT = 5
MAX_DUPS = 20
TIMEOUT_RETRIES = 5

# Initialize the logger.
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
    datefmt='%m-%d %H:%M:%S')
# The logger used by this library. Feel free to clobber it with your own, if you like, as
# long as it conforms to Python's logging.
logger = logging.getLogger('tftpy')

def tftpassert(condition, msg):
    """This function is a simple utility that will check the condition
    passed for a false state. If it finds one, it throws a TftpException
    with the message passed. This just makes the code throughout cleaner
    by refactoring."""
    if not condition:
        raise TftpException, msg

def setLogLevel(level):
    """This function is a utility function for setting the internal log level.
    The log level defaults to logging.NOTSET, so unwanted output to stdout is
    not created."""
    global logger
    logger.setLevel(level)

class TftpException(Exception):
    """This class is the parent class of all exceptions regarding the handling
    of the TFTP protocol."""
    pass

class TftpPacketWithOptions(object):
    """This class exists to permit some TftpPacket subclasses to share code
    regarding options handling. It does not inherit from TftpPacket, as the
    goal is just to share code here, and not cause diamond inheritance."""
    def __init__(self):
        self.options = None

    def setoptions(self, options):
        logger.debug("in TftpPacketWithOptions.setoptions")
        logger.debug("options: " + str(options))
        myoptions = {}
        for key in options:
            newkey = str(key)
            myoptions[newkey] = str(options[key])
            logger.debug("populated myoptions with %s = %s"
                         % (newkey, myoptions[newkey]))

        logger.debug("setting options hash to: " + str(myoptions))
        self.__options = myoptions

    def getoptions(self):
        logger.debug("in TftpPacketWithOptions.getoptions")
        return self.__options

    # Set up getter and setter on options to ensure that they are the proper
    # type. They should always be strings, but we don't need to force the
    # client to necessarily enter strings if we can avoid it.
    options = property(getoptions, setoptions)

    def decode_options(self, buffer):
        """This method decodes the section of the buffer that contains an
        unknown number of options. It returns a dictionary of option names and
        values."""
        nulls = 0
        format = "!"
        options = {}

        logger.debug("decode_options: buffer is: " + repr(buffer))
        logger.debug("size of buffer is %d bytes" % len(buffer))
        if len(buffer) == 0:
            logger.debug("size of buffer is zero, returning empty hash")
            return {}

        # Count the nulls in the buffer. Each one terminates a string.
        logger.debug("about to iterate options buffer counting nulls")
        length = 0
        for c in buffer:
            #logger.debug("iterating this byte: " + repr(c))
            if ord(c) == 0:
                logger.debug("found a null at length %d" % length)
                if length > 0:
                    format += "%dsx" % length
                    length = -1
                else:
                    raise TftpException, "Invalid options in buffer"
            length += 1
                
        logger.debug("about to unpack, format is: %s" % format)
        mystruct = struct.unpack(format, buffer)
        
        tftpassert(len(mystruct) % 2 == 0, 
                   "packet with odd number of option/value pairs")
        
        for i in range(0, len(mystruct), 2):
            logger.debug("setting option %s to %s" % (mystruct[i], mystruct[i+1]))
            options[mystruct[i]] = mystruct[i+1]

        return options

class TftpPacket(object):
    """This class is the parent class of all tftp packet classes. It is an
    abstract class, providing an interface, and should not be instantiated
    directly."""
    def __init__(self):
        self.opcode = 0
        self.buffer = None

    def encode(self):
        """The encode method of a TftpPacket takes keyword arguments specific
        to the type of packet, and packs an appropriate buffer in network-byte
        order suitable for sending over the wire.
        
        This is an abstract method."""
        raise NotImplementedError, "Abstract method"

    def decode(self):
        """The decode method of a TftpPacket takes a buffer off of the wire in
        network-byte order, and decodes it, populating internal properties as
        appropriate. This can only be done once the first 2-byte opcode has
        already been decoded, but the data section does include the entire
        datagram.
        
        This is an abstract method."""
        raise NotImplementedError, "Abstract method"

class TftpPacketInitial(TftpPacket, TftpPacketWithOptions):
    """This class is a common parent class for the RRQ and WRQ packets, as 
    they share quite a bit of code."""
    def __init__(self):
        TftpPacket.__init__(self)
        self.filename = None
        self.mode = None
        
    def encode(self):
        """Encode the packet's buffer from the instance variables."""
        tftpassert(self.filename, "filename required in initial packet")
        tftpassert(self.mode, "mode required in initial packet")

        ptype = None
        if self.opcode == 1: ptype = "RRQ"
        else:                ptype = "WRQ"
        logger.debug("Encoding %s packet, filename = %s, mode = %s"
                     % (ptype, self.filename, self.mode))
        for key in self.options:
            logger.debug("    Option %s = %s" % (key, self.options[key]))
        
        format = "!H"
        format += "%dsx" % len(self.filename)
        if self.mode == "octet":
            format += "5sx"
        else:
            raise AssertionError, "Unsupported mode: %s" % mode
        # Add options.
        options_list = []
        if self.options.keys() > 0:
            logger.debug("there are options to encode")
            for key in self.options:
                format += "%dsx" % len(key)
                format += "%dsx" % len(str(self.options[key]))
                options_list.append(key)
                options_list.append(str(self.options[key]))

        logger.debug("format is %s" % format)
        logger.debug("size of struct is %d" % struct.calcsize(format))

        self.buffer = struct.pack(format,
                                  self.opcode,
                                  self.filename,
                                  self.mode,
                                  *options_list)

        logger.debug("buffer is " + repr(self.buffer))
        return self
    
    def decode(self):
        tftpassert(self.buffer, "Can't decode, buffer is empty")

        # FIXME - this shares a lot of code with decode_options
        nulls = 0
        format = ""
        nulls = length = tlength = 0
        logger.debug("in decode: about to iterate buffer counting nulls")
        subbuf = self.buffer[2:]
        for c in subbuf:
            logger.debug("iterating this byte: " + repr(c))
            if ord(c) == 0:
                nulls += 1
                logger.debug("found a null at length %d, now have %d" 
                             % (length, nulls))
                format += "%dsx" % length
                length = -1
                # At 2 nulls, we want to mark that position for decoding.
                if nulls == 2:
                    break
            length += 1
            tlength += 1

        logger.debug("hopefully found end of mode at length %d" % tlength)
        # length should now be the end of the mode.
        tftpassert(nulls == 2, "malformed packet")
        shortbuf = subbuf[:tlength+1]
        logger.debug("about to unpack buffer with format: %s" % format)
        logger.debug("unpacking buffer: " + repr(shortbuf))
        mystruct = struct.unpack(format, shortbuf)

        tftpassert(len(mystruct) == 2, "malformed packet")
        logger.debug("setting filename to %s" % mystruct[0])
        logger.debug("setting mode to %s" % mystruct[1])
        self.filename = mystruct[0]
        self.mode = mystruct[1]

        self.options = self.decode_options(subbuf[tlength+1:])
        return self

class TftpPacketRRQ(TftpPacketInitial):
    """
        2 bytes    string   1 byte     string   1 byte
        -----------------------------------------------
RRQ/  | 01/02 |  Filename  |   0  |    Mode    |   0  |
WRQ    -----------------------------------------------
    """
    def __init__(self):
        TftpPacketInitial.__init__(self)
        self.opcode = 1

class TftpPacketWRQ(TftpPacketInitial):
    """
        2 bytes    string   1 byte     string   1 byte
        -----------------------------------------------
RRQ/  | 01/02 |  Filename  |   0  |    Mode    |   0  |
WRQ    -----------------------------------------------
    """
    def __init__(self):
        TftpPacketInitial.__init__(self)
        self.opcode = 2

class TftpPacketDAT(TftpPacket):
    """
        2 bytes    2 bytes       n bytes
        ---------------------------------
DATA  | 03    |   Block #  |    Data    |
        ---------------------------------
    """
    def __init__(self):
        TftpPacket.__init__(self)
        self.opcode = 3
        self.blocknumber = 0
        self.data = None

    def encode(self):
        """Encode the DAT packet. This method populates self.buffer, and
        returns self for easy method chaining."""
        tftpassert(len(self.data) > 0, "no point encoding empty data packet")
        format = "!HH%ds" % len(self.data)
        self.buffer = struct.pack(format, 
                                  self.opcode, 
                                  self.blocknumber, 
                                  self.data)
        return self

    def decode(self):
        """Decode self.buffer into instance variables. It returns self for
        easy method chaining."""
        # We know the first 2 bytes are the opcode. The second two are the
        # block number.
        (self.blocknumber,) = struct.unpack("!H", self.buffer[2:4])
        logger.debug("decoding DAT packet, block number %d" % self.blocknumber)
        logger.debug("should be %d bytes in the packet total" 
                     % len(self.buffer))
        # Everything else is data.
        self.data = self.buffer[4:]
        logger.debug("found %d bytes of data"
                     % len(self.data))
        return self

class TftpPacketACK(TftpPacket):
    """
        2 bytes    2 bytes
        -------------------
ACK   | 04    |   Block #  |
        --------------------
    """
    def __init__(self):
        TftpPacket.__init__(self)
        self.opcode = 4
        self.blocknumber = 0

    def encode(self):
        logger.debug("encoding ACK: opcode = %d, block = %d" 
                     % (self.opcode, self.blocknumber))
        self.buffer = struct.pack("!HH", self.opcode, self.blocknumber)
        return self

    def decode(self):
        self.opcode, self.blocknumber = struct.unpack("!HH", self.buffer)
        logger.debug("decoded ACK packet: opcode = %d, block = %d"
                     % (self.opcode, self.blocknumber))
        return self

class TftpPacketERR(TftpPacket):
    """
        2 bytes  2 bytes        string    1 byte
        ----------------------------------------
ERROR | 05    |  ErrorCode |   ErrMsg   |   0  |
        ----------------------------------------
    Error Codes

    Value     Meaning

    0         Not defined, see error message (if any).
    1         File not found.
    2         Access violation.
    3         Disk full or allocation exceeded.
    4         Illegal TFTP operation.
    5         Unknown transfer ID.
    6         File already exists.
    7         No such user.
    """
    def __init__(self):
        TftpPacket.__init__(self)
        self.opcode = 5
        self.errorcode = 0
        self.errmsg = None
        self.errmsgs = {
            1: "File not found",
            2: "Access violation",
            3: "Disk full or allocation exceeded",
            4: "Illegal TFTP operation",
            5: "Unknown transfer ID",
            6: "File already exists",
            7: "No such user",
            8: "Failed to negotiate options"
            }

    def encode(self):
        """Encode the DAT packet based on instance variables, populating
        self.buffer, returning self."""
        format = "!HH%dsx" % len(self.errmsgs[self.errorcode])
        logger.debug("encoding ERR packet with format %s" % format)
        self.buffer = struct.pack(format,
                                  self.opcode,
                                  self.errorcode,
                                  self.errmsgs[self.errorcode])
        return self

    def decode(self):
        "Decode self.buffer, populating instance variables and return self."
        tftpassert(len(self.buffer) >= 5, "malformed ERR packet")
        format = "!HH%dsx" % (len(self.buffer) - 5)
        self.opcode, self.errorcode, self.errmsg = struct.unpack(format, 
                                                                 self.buffer)
        logger.error("ERR packet - errorcode: %d, message: %s"
                     % (self.errorcode, self.errmsg))
        return self
    
class TftpPacketOACK(TftpPacket, TftpPacketWithOptions):
    """
    #  +-------+---~~---+---+---~~---+---+---~~---+---+---~~---+---+
    #  |  opc  |  opt1  | 0 | value1 | 0 |  optN  | 0 | valueN | 0 |
    #  +-------+---~~---+---+---~~---+---+---~~---+---+---~~---+---+
    """
    def __init__(self):
        TftpPacket.__init__(self)
        self.opcode = 6
        
    def encode(self):
        format = "!H" # opcode
        options_list = []
        logger.debug("in TftpPacketOACK.encode")
        for key in self.options:
            logger.debug("looping on option key %s" % key)
            logger.debug("value is %s" % self.options[key])
            format += "%dsx" % len(key)
            format += "%dsx" % len(self.options[key])
            options_list.append(key)
            options_list.append(self.options[key])
        self.buffer = struct.pack(format, self.opcode, *options_list)
        return self
    
    def decode(self):
        self.options = self.decode_options(self.buffer[2:])
        return self
    
    def match_options(self, options):
        """This method takes a set of options, and tries to match them with
        its own. It can accept some changes in those options from the server as
        part of a negotiation. Changed or unchanged, it will return a dict of
        the options so that the session can update itself to the negotiated
        options."""
        for name in self.options:
            if options.has_key(name):
                if name == 'blksize':
                    # We can accept anything between the min and max values.
                    size = self.options[name]
                    if size >= MIN_BLKSIZE and size <= MAX_BLKSIZE:
                        logger.debug("negotiated blksize of %d bytes" % size)
                        options[blksize] = size
                else:
                    raise TftpException, "Unsupported option: %s" % name
        return True

class TftpPacketFactory(object):
    """This class generates TftpPacket objects."""
    def __init__(self):
        self.classes = {
            1: TftpPacketRRQ,
            2: TftpPacketWRQ,
            3: TftpPacketDAT,
            4: TftpPacketACK,
            5: TftpPacketERR,
            6: TftpPacketOACK
            }

    def create(self, opcode):
        tftpassert(self.classes.has_key(opcode), 
                   "Unsupported opcode: %d" % opcode)
        packet = self.classes[opcode]()
        logger.debug("packet is %s" % packet)
        return packet

    def parse(self, buffer):
        """This method is used to parse an existing datagram into its
        corresponding TftpPacket object."""
        logger.debug("parsing a %d byte packet" % len(buffer))
        (opcode,) = struct.unpack("!H", buffer[:2])
        logger.debug("opcode is %d" % opcode)
        packet = self.create(opcode)
        packet.buffer = buffer
        return packet.decode()

class TftpState(object):
    """This class represents a particular state for a TFTP Session. It encapsulates a
    state, kind of like an enum. The states mean the following:
    nil - Session not yet established
    rrq - Just sent RRQ in a download, waiting for response
    wrq - Just sent WRQ in an upload, waiting for response
    dat - Transferring data
    oack - Received oack, negotiating options
    ack - Acknowledged oack, awaiting response
    err - Fatal problems, giving up
    fin - Transfer completed
    """
    states = ['nil',
              'rrq',
              'wrq',
              'dat',
              'oack',
              'ack',
              'err',
              'fin']
    
    def __init__(self, state='nil'):
        self.state = state
        
    def getState(self):
        return self.__state
    
    def setState(self, state):
        if state in TftpState.states:
            self.__state = state
            
    state = property(getState, setState)

class TftpSession(object):
    """This class is the base class for the tftp client and server. Any shared
    code should be in this class."""
    def __init__(self):
        "Class constructor. Note that the state property must be a TftpState object."
        self.options = None
        self.state = TftpState()
        self.dups = 0
        self.errors = 0

class TftpClient(TftpSession):
    """This class is an implementation of a tftp client."""
    def __init__(self, host, port, options={}):
        """This constructor returns an instance of TftpClient, taking the
        remote host, the remote port, and the filename to fetch."""
        TftpSession.__init__(self)
        self.host = host
        self.port = port
        self.options = options
        if self.options.has_key('blksize'):
            size = self.options['blksize']
            tftpassert(types.IntType == type(size), "blksize must be an int")
            if size < MIN_BLKSIZE or size > MAX_BLKSIZE:
                raise TftpException, "Invalid blksize: %d" % size
        else:
            self.options['blksize'] = DEF_BLKSIZE
        # Support other options here? timeout time, retries, etc?
        
        # The remote sending port, to identify the connection.
        self.rport = None
        
    def gethost(self):
        "Simple getter method."
        return self.__host
    
    def sethost(self, host):
        """Setter method that also sets the address property as a result
        of the host that is set."""
        self.__host = host
        self.address = socket.gethostbyname(host)
        
    host = property(gethost, sethost)

    def download(self, filename, output, packethook=None, timeout=SOCK_TIMEOUT):
        """This method initiates a tftp download from the configured remote
        host, requesting the filename passed. It saves the file to a local
        file specified in the output parameter. If a packethook is provided,
        it must be a function that takes a single parameter, which will be a
        copy of each DAT packet received in the form of a TftpPacketDAT
        object. The timeout parameter may be used to override the default
        SOCK_TIMEOUT setting, which is the amount of time that the client will
        wait for a receive packet to arrive."""
        # Open the output file.
        # FIXME - need to support alternate return formats than files?
        outputfile = open(output, "wb")
        recvpkt = None
        curblock = 0
        dups = {}
        start_time = time.time()
        bytes = 0

        tftp_factory = TftpPacketFactory()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)

        logger.info("Sending tftp download request to %s" % self.host)
        logger.info("    filename -> %s" % filename)
        pkt = TftpPacketRRQ()
        pkt.filename = filename
        pkt.mode = "octet" # FIXME - shouldn't hardcode this
        pkt.options = self.options
        sock.sendto(pkt.encode().buffer, (self.host, self.port))
        self.state.state = 'rrq'
        
        timeouts = 0
        while True:
            try:
                (buffer, (raddress, rport)) = sock.recvfrom(MAX_BLKSIZE)
            except socket.timeout, err:
                timeouts += 1
                if timeouts >= TIMEOUT_RETRIES:
                    raise TftpException, "Hit max timeouts, giving up."
                else:
                    logger.warn("Timeout waiting for traffic, retrying...")
                    continue

            recvpkt = tftp_factory.parse(buffer)

            logger.debug("Received %d bytes from %s:%s" 
                         % (len(buffer), raddress, rport))
            
            # Check for known "connection".
            if raddress != self.address:
                logger.warn("Received traffic from %s, expected host %s. Discarding"
                            % (raddress, self.host))
                continue
            if self.rport and self.rport != rport:
                logger.warn("Received traffic from %s:%s but we're "
                            "connected to %s:%s. Discarding."
                            % (raddress, rport,
                            self.host, self.rport))
                continue
            
            if not self.rport and self.state.state == 'rrq':
                self.rport = rport
                logger.debug("Set remote port for session to %s" % rport)
            
            if isinstance(recvpkt, TftpPacketDAT):
                logger.debug("recvpkt.blocknumber = %d" % recvpkt.blocknumber)
                logger.debug("curblock = %d" % curblock)
                if recvpkt.blocknumber == curblock+1:
                    logger.debug("good, received block %d in sequence" 
                                % recvpkt.blocknumber)
                    curblock += 1

                        
                    # ACK the packet, and save the data.
                    logger.info("sending ACK to block %d" % curblock)
                    logger.debug("ip = %s, port = %s" % (self.host, self.port))
                    ackpkt = TftpPacketACK()
                    ackpkt.blocknumber = curblock
                    sock.sendto(ackpkt.encode().buffer, (self.host, self.rport))
                    
                    logger.debug("writing %d bytes to output file" 
                                % len(recvpkt.data))
                    outputfile.write(recvpkt.data)
                    bytes += len(recvpkt.data)
                    # If there is a packethook defined, call it.
                    if packethook:
                        packethook(recvpkt)
                    # Check for end-of-file, any less than full data packet.
                    if len(recvpkt.data) < self.options['blksize']:
                        logger.info("end of file detected")
                        break

                elif recvpkt.blocknumber == curblock:
                    logger.warn("dropping duplicate block %d" % curblock)
                    if dups.has_key(curblock):
                        dups[curblock] += 1
                    else:
                        dups[curblock] = 1
                    tftpassert(dups[curblock] < MAX_DUPS,
                            "Max duplicates for block %d reached" % curblock)
                    logger.debug("ACKing block %d again, just in case" % curblock)
                    ackpkt = TftpPacketACK()
                    ackpkt.blocknumber = curblock
                    sock.sendto(ackpkt.encode().buffer, (self.host, self.rport))

                else:
                    msg = "Whoa! Received block %d but expected %d" % (recvpkt.blocknumber, 
                                                                    curblock+1)
                    logger.error(msg)
                    raise TftpException, msg

            # Check other packet types.
            elif isinstance(recvpkt, TftpPacketOACK):
                if not self.state.state == 'rrq':
                    self.errors += 1
                    logger.error("Received OACK in state %s" % self.state.state)
                    continue
                
                self.state.state = 'oack'
                logger.info("Received OACK from server.")
                if recvpkt.options.keys() > 0:
                    if recvpkt.match_options(self.options):
                        logger.info("Successful negotiation of options")
                        for key in self.options:
                            logger.info("    %s = %s" % (key, self.options[key]))
                        logger.debug("sending ACK to OACK")
                        ackpkt = TftpPacketACK()
                        ackpkt.blocknumber = 0
                        sock.sendto(ackpkt.encode().buffer, (self.host, self.rport))
                        self.state.state = 'ack'
                    else:
                        logger.error("failed to negotiate options")
                        errpkt = TftpPacketERR()
                        errpkt.errorcode = 8
                        sock.sendto(errpkt.encode().buffer, (self.host, self.rport))
                        self.state.state = 'err'
                        raise TftpException, "Failed to negotiate options"

            elif isinstance(recvpkt, TftpPacketACK):
                # Umm, we ACK, the server doesn't.
                self.state.state = 'err'
                tftpassert(False, "Received ACK from server while in download")

            elif isinstance(recvpkt, TftpPacketERR):
                self.state.state = 'err'
                tftpassert(False, "Received ERR from server: " + recvpkt)

            elif isinstance(recvpkt, TftpPacketWRQ):
                self.state.state = 'err'
                tftpassert(False, "Received WRQ from server: " + recvpkt)

            else:
                self.state.state = 'err'
                tftpassert(False, "Received unknown packet type from server: "
                        + recvpkt)


        # end while

        end_time = time.time()
        duration = end_time - start_time
        outputfile.close()
        logger.info('')
        logger.info("Downloaded %d bytes in %d seconds" % (bytes, duration))
        bps = (bytes * 8.0) / duration
        kbps = bps / 1024.0
        logger.info("Average rate: %.2f kbps" % kbps)
        dupcount = 0
        for key in dups:
            dupcount += dups[key]
        logger.info("Received %d duplicate packets" % dupcount)
