import twisted.web.server
from twisted.protocols import basic
from twisted.internet import protocol, reactor
from twisted.web import http

class SyncSendContent:
    """
    Takes data written by a send request and writes it to a receive request
    """
    def __init__(self, request, key):
        """
        Prepare to send a file from a sender to a receiver.
        @param request:     The sender's POST or PUT request
        @param key:         The sender's email address or some other unique key
        """
        assert request.channel._command in ('POST', 'PUT')
        self.request = request
        self.key = key

        # When we receive the first chunk of an uploaded file, if the receiver hasn't connected
        # yet, we'll need to store that first chunk while we wait for the receiver to connect.
        self.buffer = None

    def seek(self, *args, **kwargs):
        """
        Request.requestReceived() calls seek(0,0), so stub it out here to avoid an AttributeError
        """
        pass

    def write(self, data):
        """
        Receive data from the sender. If the receiver has connected, send the data, otherwise
        buffer this chunk of data and pause sending until the receiver connects.
        """
        import time
        time.sleep(1)
        if self.key in get_requests:
            get_request = get_requests[self.key]
            print '%s: writing %s' % (
                id(self.request),
                (len(self.buffer) if self.buffer is not None else 0) + len(data),
            )
            if self.buffer is not None:
                # We have just resumed producing
                get_request.write(self.buffer)
                self.buffer = None
            get_request.write(data)
        else:
            self.buffer = data
            self.request.channel.pauseProducing()

    def close(self, *args, **kwargs):
        get_requests[self.key].finish()
        del get_requests[self.key]
        del self.request # Break circular reference to aid garbage collection

# Users start sending or receiving files by entering an email address or
# some other unique key. These dicts map from keys to GET requests (the
# receivers) and from keys to PUT or POST requests (the receivers)
post_requests = {}
get_requests = {}

class SyncSendRequest(http.Request):
    def gotLength(self, length):
        """
        This request could either be the sender's POST or PUT request, or it could be the receiver's
        GET request. Either way, set my key based on the URI.
        """
        # HACK: access internal variable, since self.path isn't set until all content has been uploaded
        self.key = self.channel._path
        print self.channel._command, self.key

        # HACK: access internal variable, since self.method isn't set until all content has been uploaded
        if self.channel._command in ('PUT', 'POST'):
            # Instead of using a StringIO or temp file as Twisted does, make a fake file object that
            # will funnel data from the sender to the receiver
            self.content = SyncSendContent(self, self.key)
            post_requests[self.key] = self
        else:
            # Normal processing for GET requests
            http.Request.gotLength(self, length)

    def process(self):
        """
        If we're processing an upload, this method is called when all content has been uploaded. If we're
        processing a download, this is called when we receive the whole GET request.
        """
        if self.method in ('POST', 'PUT'):
            self.write('done\n')
            del post_requests[self.key]
            self.finish()
            return twisted.web.server.NOT_DONE_YET
        elif self.method == 'GET':
            get_requests[self.key] = self
            if self.key in post_requests:
                post_requests[self.key].channel.resumeProducing()
            return twisted.web.server.NOT_DONE_YET
        else:
            self.setResponseCode(405, 'Method not allowed')

class SyncSendHttp(http.HTTPChannel):
    requestFactory = SyncSendRequest

class SyncSendHttpFactory(http.HTTPFactory):
    protocol = SyncSendHttp

if __name__ == "__main__":
    from twisted.internet import reactor
    reactor.listenTCP(8000, SyncSendHttpFactory())
    reactor.run()
