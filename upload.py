# system imports
from cStringIO import StringIO
import tempfile
import base64, binascii
import cgi
import socket
import math
import time
import calendar
import warnings
import os
from urlparse import urlparse as _urlparse

from zope.interface import implements

# twisted imports
from twisted.internet import interfaces, reactor, protocol, address
from twisted.internet.defer import Deferred
from twisted.protocols import policies, basic
from twisted.python import log
try: # try importing the fast, C version
    from twisted.protocols._c_urlarg import unquote
except ImportError:
    from urllib import unquote

from twisted.web.http_headers import _DictHeaders, Headers
from twisted.web.http import protocol_version, datetimeToString, toChunk, RESPONSES, Request

class FileDownloadRequest(Request):
    pass


# response codes that must have empty bodies
NO_BODY_CODES = (204, 304)

class FileUploadRequest:
    """
    A HTTP request for uploading files. Copied and adapted from twisted.web.http.Request.

    Many simplifications over Twisted's Request: no queueing, no cookies, no authentication, no SSL
    """
    implements(interfaces.IConsumer)

    producer = None
    finished = 0
    method = "(no method yet)"
    clientproto = "(no clientproto yet)"
    uri = "(no uri yet)"
    startedWriting = 0
    chunked = 0
    sentLength = 0 # content-length of response, or total bytes sent via chunking
    etag = None
    lastModified = None
    args = None
    path = None
    content = None
    _disconnected = False

    def __init__(self, channel):
        """
        @param channel: the channel we're connected to.
        """
        self.notifications = []
        self.channel = channel
        self.requestHeaders = Headers()
        self.received_cookies = {}
        self.responseHeaders = Headers()
        self.transport = self.channel.transport


    def __setattr__(self, name, value):
        """
        Support assignment of C{dict} instances to C{received_headers} for
        backwards-compatibility.
        """
        if name == 'received_headers':
            # A property would be nice, but Request is classic.
            self.requestHeaders = headers = Headers()
            for k, v in value.iteritems():
                headers.setRawHeaders(k, [v])
        elif name == 'requestHeaders':
            self.__dict__[name] = value
            self.__dict__['received_headers'] = _DictHeaders(value)
        elif name == 'headers':
            self.responseHeaders = headers = Headers()
            for k, v in value.iteritems():
                headers.setRawHeaders(k, [v])
        elif name == 'responseHeaders':
            self.__dict__[name] = value
            self.__dict__['headers'] = _DictHeaders(value)
        else:
            self.__dict__[name] = value


    def _cleanup(self):
        """
        Called when have finished responding and are no longer queued.
        """
        if self.producer:
            log.err(RuntimeError("Producer was not unregistered for %s" % self.uri))
            self.unregisterProducer()
        self.channel.requestDone(self)
        del self.channel
        for d in self.notifications:
            d.callback(None)
        self.notifications = []

    def gotLength(self, length):
        """
        Called when HTTP channel got length of content in this request.

        This method is not intended for users.

        @param length: The length of the request body, as indicated by the
            request headers.  C{None} if the request headers do not indicate a
            length.
        """
        self.content_length = length


    def handleContentChunk(self, data):
        """
        Write a chunk of data.

        This method is not intended for users.
        """
        self.sendData(data)

    # consumer interface

    def registerProducer(self, producer, streaming):
        """
        Register a producer.
        """
        if self.producer:
            raise ValueError, "registering producer %s before previous one (%s) was unregistered" % (producer, self.producer)

        self.streamingProducer = streaming
        self.producer = producer
        self.transport.registerProducer(producer, streaming)

    def unregisterProducer(self):
        """
        Unregister the producer.
        """
        self.producer = None

    # private http response methods


    # The following is the public interface that people should be
    # writing to.
    def getHeader(self, key):
        """
        Get an HTTP request header.

        @type key: C{str}
        @param key: The name of the header to get the value of.

        @rtype: C{str} or C{NoneType}
        @return: The value of the specified header, or C{None} if that header
            was not present in the request.
        """
        value = self.requestHeaders.getRawHeaders(key)
        if value is not None:
            return value[-1]



    def notifyFinish(self):
        """
        Notify when the response to this request has finished.

        @rtype: L{Deferred}

        @return: A L{Deferred} which will be triggered when the request is
            finished -- with a C{None} value if the request finishes
            successfully or with an error if the request is interrupted by an
            error (for example, the client closing the connection prematurely).
        """
        self.notifications.append(Deferred())
        return self.notifications[-1]


    def finish(self):
        """
        Indicate that all response data has been written to this L{Request}.
        """
        if self._disconnected:
            raise RuntimeError(
                "Request.finish called on a request after its connection was lost; "
                "use Request.notifyFinish to keep track of this.")
        if self.finished:
            warnings.warn("Warning! request.finish called twice.", stacklevel=2)
            return

        if not self.startedWriting:
            # write headers
            self.write('')

        if self.chunked:
            # write last chunk and closing CRLF
            self.transport.write("0\r\n\r\n")

        # log request
        if hasattr(self.channel, "factory"):
            self.channel.factory.log(self)

        self.finished = 1
        if not self.queued:
            self._cleanup()

    def write(self, data):
        """
        Write some data as a result of an HTTP request.  The first
        time this is called, it writes out response data.

        @type data: C{str}
        @param data: Some bytes to be sent as part of the response body.
        """
        if not self.startedWriting:
            self.startedWriting = 1
            version = self.clientproto
            l = []
            l.append('%s %s %s\r\n' % (version, self.code,
                                       self.code_message))
            # if we don't have a content length, we send data in
            # chunked mode, so that we can support pipelining in
            # persistent connections.
            if ((version == "HTTP/1.1") and
                (self.responseHeaders.getRawHeaders('content-length') is None) and
                self.method != "HEAD" and self.code not in NO_BODY_CODES):
                l.append("%s: %s\r\n" % ('Transfer-Encoding', 'chunked'))
                self.chunked = 1

            if self.lastModified is not None:
                if self.responseHeaders.hasHeader('last-modified'):
                    log.msg("Warning: last-modified specified both in"
                            " header list and lastModified attribute.")
                else:
                    self.responseHeaders.setRawHeaders(
                        'last-modified',
                        [datetimeToString(self.lastModified)])

            for name, values in self.responseHeaders.getAllRawHeaders():
                for value in values:
                    l.append("%s: %s\r\n" % (name, value))

            l.append("\r\n")

            self.transport.writeSequence(l)

            # if this is a "HEAD" request, we shouldn't return any data
            if self.method == "HEAD":
                self.write = lambda data: None
                return

            # for certain result codes, we should never return any data
            if self.code in NO_BODY_CODES:
                self.write = lambda data: None
                return

        self.sentLength = self.sentLength + len(data)
        if data:
            if self.chunked:
                self.transport.writeSequence(toChunk(data))
            else:
                self.transport.write(data)

    def setResponseCode(self, code, message=None):
        """
        Set the HTTP response code.
        """
        if not isinstance(code, (int, long)):
            raise TypeError("HTTP response code must be int or long")
        self.code = code
        if message:
            self.code_message = message
        else:
            self.code_message = RESPONSES.get(code, "Unknown Status")


    def setHeader(self, name, value):
        """
        Set an HTTP response header.  Overrides any previously set values for
        this header.

        @type name: C{str}
        @param name: The name of the header for which to set the value.

        @type value: C{str}
        @param value: The value to set for the named header.
        """
        self.responseHeaders.setRawHeaders(name, [value])

    def getAllHeaders(self):
        """
        Return dictionary mapping the names of all received headers to the last
        value received for each.

        Since this method does not return all header information,
        C{self.requestHeaders.getAllRawHeaders()} may be preferred.
        """
        headers = {}
        for k, v in self.requestHeaders.getAllRawHeaders():
            headers[k.lower()] = v[-1]
        return headers


    def getRequestHostname(self):
        """
        Get the hostname that the user passed in to the request.

        This will either use the Host: header (if it is available) or the
        host we are listening on if the header is unavailable.

        @returns: the requested hostname
        @rtype: C{str}
        """
        # XXX This method probably has no unit tests.  I changed it a ton and
        # nothing failed.
        host = self.getHeader('host')
        if host:
            return host.split(':', 1)[0]
        return self.getHost().host


    def getHost(self):
        """
        Get my originally requesting transport's host.

        Don't rely on the 'transport' attribute, since Request objects may be
        copied remotely.  For information on this method's return value, see
        twisted.internet.tcp.Port.
        """
        return self.host

    def setHost(self, host, port, ssl=0):
        """
        Change the host and port the request thinks it's using.

        This method is useful for working with reverse HTTP proxies (e.g.
        both Squid and Apache's mod_proxy can do this), when the address
        the HTTP client is using is different than the one we're listening on.

        For example, Apache may be listening on https://www.example.com, and then
        forwarding requests to http://localhost:8080, but we don't want HTML produced
        by Twisted to say 'http://localhost:8080', they should say 'https://www.example.com',
        so we do::

           request.setHost('www.example.com', 443, ssl=1)

        @type host: C{str}
        @param host: The value to which to change the host header.

        @type ssl: C{bool}
        @param ssl: A flag which, if C{True}, indicates that the request is
            considered secure (if C{True}, L{isSecure} will return C{True}).
        """
        self._forceSSL = ssl
        self.requestHeaders.setRawHeaders("host", [host])
        self.host = address.IPv4Address("TCP", host, port)


    def getClientIP(self):
        """
        Return the IP address of the client who submitted this request.

        @returns: the client IP address
        @rtype: C{str}
        """
        if isinstance(self.client, address.IPv4Address):
            return self.client.host
        else:
            return None

    def isSecure(self):
        """
        Return True if this request is using a secure transport.

        Normally this method returns True if this request's HTTPChannel
        instance is using a transport that implements ISSLTransport.

        This will also return True if setHost() has been called
        with ssl=True.

        @returns: True if this request is secure
        @rtype: C{bool}
        """
        if self._forceSSL:
            return True
        transport = getattr(getattr(self, 'channel', None), 'transport', None)
        if interfaces.ISSLTransport(transport, None) is not None:
            return True
        return False

    def _authorize(self):
        # Authorization, (mostly) per the RFC
        try:
            authh = self.getHeader("Authorization")
            if not authh:
                self.user = self.password = ''
                return
            bas, upw = authh.split()
            if bas.lower() != "basic":
                raise ValueError
            upw = base64.decodestring(upw)
            self.user, self.password = upw.split(':', 1)
        except (binascii.Error, ValueError):
            self.user = self.password = ""
        except:
            log.err()
            self.user = self.password = ""

    def getUser(self):
        """
        Return the HTTP user sent with this request, if any.

        If no user was supplied, return the empty string.

        @returns: the HTTP user, if any
        @rtype: C{str}
        """
        try:
            return self.user
        except:
            pass
        self._authorize()
        return self.user

    def getPassword(self):
        """
        Return the HTTP password sent with this request, if any.

        If no password was supplied, return the empty string.

        @returns: the HTTP password, if any
        @rtype: C{str}
        """
        try:
            return self.password
        except:
            pass
        self._authorize()
        return self.password

    def getClient(self):
        if self.client.type != 'TCP':
            return None
        host = self.client.host
        try:
            name, names, addresses = socket.gethostbyaddr(host)
        except socket.error:
            return host
        names.insert(0, name)
        for name in names:
            if '.' in name:
                return name
        return names[0]


    def connectionLost(self, reason):
        """
        There is no longer a connection for this request to respond over.
        Clean up anything which can't be useful anymore.
        """
        self._disconnected = True
        self.channel = None
        if self.content is not None:
            self.content.close()
        for d in self.notifications:
            d.errback(reason)
        self.notifications = []



class HTTPFileUploadChannel(basic.LineReceiver, policies.TimeoutMixin):
    """
    A receiver for HTTP requests.

    @ivar _transferDecoder: C{None} or an instance of
        L{_ChunkedTransferDecoder} if the request body uses the I{chunked}
        Transfer-Encoding.
    """

    maxHeaders = 500 # max number of headers allowed per request

    length = 0
    persistent = 1
    __header = ''
    __first_line = 1
    __content = None

    # set in instances or subclasses
    requestFactory = Request

    _savedTimeOut = None
    _receivedHeaderCount = 0

    def __init__(self):
        # the request queue
        self.requests = []
        self._transferDecoder = None


    def connectionMade(self):
        self.setTimeout(self.timeOut)

    def lineReceived(self, line):
        self.resetTimeout()

        if self.__first_line:
            # if this connection is not persistent, drop any data which
            # the client (illegally) sent after the last request.
            if not self.persistent:
                self.dataReceived = self.lineReceived = lambda *args: None
                return

            # IE sends an extraneous empty line (\r\n) after a POST request;
            # eat up such a line, but only ONCE
            if not line and self.__first_line == 1:
                self.__first_line = 2
                return


            self.__first_line = 0
            parts = line.split()
            if len(parts) != 3:
                self.transport.write("HTTP/1.1 400 Bad Request\r\n\r\n")
                self.transport.loseConnection()
                return
            command, request, version = parts
            if command not in ('POST', 'GET'):
                self.transport.write("HTTP/1.1 405 Method Not Allowed\r\n\r\n")
                self.transport.loseConnection()
                return

            self._command = command
            self._path = request
            self._version = version

            # create a new Request object
            request = FileUploadRequest(self) if self._command == 'POST' else FileDownloadRequest(self)
            self.requests.append(request)
        elif line == '':
            if self.__header:
                self.headerReceived(self.__header)
            self.__header = ''
            self.allHeadersReceived()
            if self.length == 0:
                self.allContentReceived()
            else:
                self.setRawMode()
        elif line[0] in ' \t':
            self.__header = self.__header+'\n'+line
        else:
            if self.__header:
                self.headerReceived(self.__header)
            self.__header = line


    def _finishRequestBody(self, data):
        self.allContentReceived()
        self.setLineMode(data)


    def headerReceived(self, line):
        """
        Do pre-processing (for content-length) and store this header away.
        Enforce the per-request header limit.

        @type line: C{str}
        @param line: A line from the header section of a request, excluding the
            line delimiter.
        """
        header, data = line.split(':', 1)
        header = header.lower()
        data = data.strip()
        if header == 'content-length':
            self.length = int(data)
            self._transferDecoder = _IdentityTransferDecoder(
                self.length, self.requests[-1].handleContentChunk, self._finishRequestBody)
        elif header == 'transfer-encoding' and data.lower() == 'chunked':
            self.length = None
            self._transferDecoder = _ChunkedTransferDecoder(
                self.requests[-1].handleContentChunk, self._finishRequestBody)

        reqHeaders = self.requests[-1].requestHeaders
        values = reqHeaders.getRawHeaders(header)
        if values is not None:
            values.append(data)
        else:
            reqHeaders.setRawHeaders(header, [data])

        self._receivedHeaderCount += 1
        if self._receivedHeaderCount > self.maxHeaders:
            self.transport.write("HTTP/1.1 400 Bad Request\r\n\r\n")
            self.transport.loseConnection()


    def allContentReceived(self):
        command = self._command
        path = self._path
        version = self._version

        # reset ALL state variables, so we don't interfere with next request
        self.length = 0
        self._receivedHeaderCount = 0
        self.__first_line = 1
        self._transferDecoder = None
        del self._command, self._path, self._version

        # Disable the idle timeout, in case this request takes a long
        # time to finish generating output.
        if self.timeOut:
            self._savedTimeOut = self.setTimeout(None)

        req = self.requests[-1]
        req.requestReceived(command, path, version)

    def rawDataReceived(self, data):
        self.resetTimeout()
        self._transferDecoder.dataReceived(data)


    def allHeadersReceived(self):
        req = self.requests[-1]
        req.parseCookies()
        self.persistent = self.checkPersistence(req, self._version)
        req.gotLength(self.length)


    def checkPersistence(self, request, version):
        """
        Check if the channel should close or not.

        @param request: The request most recently received over this channel
            against which checks will be made to determine if this connection
            can remain open after a matching response is returned.

        @type version: C{str}
        @param version: The version of the request.

        @rtype: C{bool}
        @return: A flag which, if C{True}, indicates that this connection may
            remain open to receive another request; if C{False}, the connection
            must be closed in order to indicate the completion of the response
            to C{request}.
        """
        connection = request.requestHeaders.getRawHeaders('connection')
        if connection:
            tokens = map(str.lower, connection[0].split(' '))
        else:
            tokens = []

        # HTTP 1.0 persistent connection support is currently disabled,
        # since we need a way to disable pipelining. HTTP 1.0 can't do
        # pipelining since we can't know in advance if we'll have a
        # content-length header, if we don't have the header we need to close the
        # connection. In HTTP 1.1 this is not an issue since we use chunked
        # encoding if content-length is not available.

        #if version == "HTTP/1.0":
        #    if 'keep-alive' in tokens:
        #        request.setHeader('connection', 'Keep-Alive')
        #        return 1
        #    else:
        #        return 0
        if version == "HTTP/1.1":
            if 'close' in tokens:
                request.responseHeaders.setRawHeaders('connection', ['close'])
                return False
            else:
                return True
        else:
            return False


    def requestDone(self, request):
        """
        Called by first request in queue when it is done.
        """
        if request != self.requests[0]: raise TypeError
        del self.requests[0]

        if self.persistent:
            # notify next request it can start writing
            if self.requests:
                self.requests[0].noLongerQueued()
            else:
                if self._savedTimeOut:
                    self.setTimeout(self._savedTimeOut)
        else:
            self.transport.loseConnection()

    def timeoutConnection(self):
        log.msg("Timing out client: %s" % str(self.transport.getPeer()))
        policies.TimeoutMixin.timeoutConnection(self)

    def connectionLost(self, reason):
        self.setTimeout(None)
        for request in self.requests:
            request.connectionLost(reason)