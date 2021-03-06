#hgvm-builder transparentunzip.py: Ungzip streams transparently if needed

import logging
import zlib

# Get a submodule-global logger
Logger = logging.getLogger("transparentunzip")

class TransparentUnzip(object):
    """
    A class that represents a transparently-un-gzipping stream.
    
    Only decompresses if necessary.
    """
    
    def __init__(self, stream):
        """
        Encapsulate the given stream in an unzipper.
        """
        
        # Keep the stream
        self.stream = stream
        
        # Make a decompressor with the accept a gzip header flag.
        # See <http://stackoverflow.com/a/22311297/402891>.
        # Will get None'd out after we're done decompressing and it is flushed.
        self.decompressor = zlib.decompressobj(zlib.MAX_WBITS + 16)
        
        # Are we really compressed? This gets set to True if we successfully
        # read the first block, and False if we failed to read the first block.
        # If it's False, there's no need to try to decompress any more blocks.
        self.header_read = None
        
        # We need to do lines ourselves, so we need to keep a buffer
        self.buffer = ""
        
        # Track out throughput
        self.compressed_bytes = 0
        self.uncompressed_bytes = 0
        
    def read(self, size):
        """
        Read size or fewer uncompressed bytes. All uncompressed bytes must flow
        out through this function.
        
        """
        
        while size > len(self.buffer) and self.buffer_chunk():
            # Loop until we have enough bytes or run out of input
            pass
        
        # Now we have enough bytes in the buffer, or at least as many as we are
        # going to get.
        
        # Pull off the bytes we were asked for
        part = self.buffer[0:size]
        # Leave the rest
        self.buffer = self.buffer[size:]
        
        self.uncompressed_bytes += len(part)
        
        return part
            
    def buffer_chunk(self):
        """
        Try to add data to the buffer. Returns true if data could be read, and
        false if there is no more data.
        """
        
        if (self.decompressor is not None and
            len(self.decompressor.unused_data) > 0):
            # We finished decompressing, but there's more data (probably another
            # concatenated gzip block). We need to decompress it. So start
            # again.
            
            # Flush anything we haven't flushed
            self.buffer += self.decompressor.flush()
            # Treat whatever was left over as new, probably-compressed data
            compressed = self.decompressor.unused_data
            # Make a new decompressor to use
            self.decompressor = zlib.decompressobj(zlib.MAX_WBITS + 16)
            # Leave header_read as true, because if the first block is gzip-
            # compressed all the other ones have to be too.
            Logger.debug("Recycled {} bytes".format(len(compressed)))
        else:
            # No leftover data from the last compressed bgzip block.
            # Try reading from the stream.
            compressed = self.stream.read(16 * 2 ** 10)
            self.compressed_bytes += len(compressed)
            Logger.debug("Read {} bytes".format(len(compressed)))
        
        if compressed == "":
            # We are out of data in the stream. But maybe there's more in
            # our decompressor?
            Logger.debug("Out of input data")
            if self.decompressor is not None and self.header_read:
                # No more input data, but we did sucessfully start
                # decompressing. Flush out the output data.
                Logger.debug("Had buffer length {}".format(
                    len(self.buffer)))
                decompressed = self.decompressor.flush()
                Logger.debug("Got {} bytes from flush with {} unconsumed and"
                    " {} trailing".format(len(decompressed),
                    len(self.decompressor.unconsumed_tail),
                    len(self.decompressor.unused_data)))
                self.buffer += decompressed
                self.decompressor = None
                Logger.debug("Flushed to buffer length {}".format(
                    len(self.buffer)))
                return True
            else:
                # Otherwise there's just no more data
                return False
        
        # If we didn't break, we got some data from the stream.
        if self.header_read is None:
            # Try decompressing the first block
            try:
                decompressed = self.decompressor.decompress(compressed)
                Logger.debug("Got {} bytes from {} bytes with {} unconsumed and"
                    " {} trailing".format(len(decompressed), len(compressed),
                    len(self.decompressor.unconsumed_tail),
                    len(self.decompressor.unused_data)))
                self.buffer += decompressed
                # We sucessfully found the headers we needed
                self.header_read = True
                Logger.debug("Is compressed")
            except zlib.error:
                # Just skip decompressing; it's probably not actually
                # compressed.
                self.buffer += compressed
                # We looked and didn't find a valid compressed header
                self.header_read = False
                Logger.debug("Is not compressed")
                
        else:
            # We know if we should be compressed or not
            Logger.debug("Extend buffer from {}".format(len(self.buffer)))
            if self.header_read:
                # We do need to decompress
                decompressed = self.decompressor.decompress(compressed)
                Logger.debug("Got {} bytes from {} bytes with {} unconsumed and"
                    " {} trailing".format(len(decompressed), len(compressed),
                    len(self.decompressor.unconsumed_tail),
                    len(self.decompressor.unused_data)))
                self.buffer += decompressed
            else:
                # We don't need to decompress at all
                self.buffer += compressed
            Logger.debug("Extend buffer to {}".format(len(self.buffer)))
                
        # If we didn't EOF, we added something to the buffer.
        return True
        
    def __iter__(self):
        """
        Get an iterator over lines in the stream. We are our own iterator.
        """
        return self
        
    def next(self):
        """
        Function as an iterator over lines.
        """
        
        # Read a line
        line = self.readline()
        
        if line == "":
            # No trailing newline only happens at the end of the file
            Logger.debug("No trailing newline, so stop iteration")
            raise StopIteration
        elif line[-1] == "\n":
            Logger.debug("Found entire line of length {}".format(len(line)))
        else:
            Logger.debug("Found partial line of length {}".format(len(line)))
            
        # If we have any data, return it
        return line
        
    def readline(self, max_bytes=None):
        """
        Return the next line with trailing "/n", or "" if there is no next line.
        
        Won't return more than max_bytes bytes.
        
        """
        
        # See if we have a line to spit out
        newline_index = self.buffer.find("\n")
        # Remember the last character we could have checked
        checked = len(self.buffer)
        
        Logger.debug("Start with newline at {}, checked through {}".format(
            newline_index, checked))
        
        while (newline_index == -1 and 
            (max_bytes is None or len(self.buffer) < max_bytes) and
            self.buffer_chunk()):
            # While we haven't found a newline, we haven't gotten too many
            # bytes, and we still have data, keep looking for newlines in the
            # new data.
            newline_index = self.buffer.find("\n", checked)
            checked = len(self.buffer)
            
            Logger.debug("Newline at {}, checked through {}".format(
                newline_index, checked))
            
        if newline_index == -1:
            # Never found a newline
            if max_bytes is None:
                # Read out the whole buffer
                Logger.debug("Dump buffer")
                return self.read(len(self.buffer))
            else:
                # Read out the bytes we were asked for
                Logger.debug("Hit limit")
                return self.read(max_bytes)
        else:
            # If we found a newline, read out all the bytes through it
            return self.read(newline_index + 1)
            
    def start_stats(self):
        """
        Reset byte stat tracking
        """
        
        self.compressed_bytes = 0
        self.uncompressed_bytes = 0
        
    def get_stats(self):
        """
        Return the number of compressed, uncompressed bytes processed.
        """
        
        return self.compressed_bytes, self.uncompressed_bytes        
