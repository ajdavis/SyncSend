import twisted.web.server
from twisted.protocols import basic
from twisted.internet import protocol, reactor
from twisted.web import http

class SyncSendContent:
    """
    Act like a file
    """
    def __init__(self, request):
        self.request = request
        self.buffer = None

    def seek(self, *args, **kwargs):
        pass

    def write(self, data):
        if get_request:
            if self.buffer is not None:
                # We have just resumed producing
                get_request.write(self.buffer)
                self.buffer = None
            get_request.write(data)
        else:
            print 'channel id', id(self.request.channel)
            self.buffer = data
            self.request.channel.pauseProducing()

    def close(self, *args, **kwargs):
        global get_request
        if get_request:
            get_request.finish()
            get_request = None
        del self.request # Break circular reference to aid garbage collection

post_request = None
get_request = None

class SyncSendRequest(http.Request):
#    def gotLength(self, length):
#        print 'length: %s' % length
#        http.Request.gotLength(self, length)

    def gotLength(self, length):
        global post_request

        self.contentSoFar = 0
        self.content = SyncSendContent(self)    

        # HACK: access internal variable, since self.method isn't set until all content has been uploaded
        if self.channel._command in ('PUT', 'POST'):
            post_request = self

    def handleContentChunk(self, data):
        self.contentSoFar += len(data)
        print 'chunk: %s, %s to go' % (len(data), self.channel.length - self.contentSoFar)
        http.Request.handleContentChunk(self, data)
#        if self.contentSoFar >= self.channel.length:
#            self.channel.allContentReceived()
#            self.write('done\n')
#            self.finish()

    def process(self):
        """
        If we're processing an upload, this method is called when all content has been uploaded. If we're
        processing a download, this is called when we receive the whole GET request.
        """
        global get_request, post_request
        if self.method in ('POST', 'PUT'):
            self.write('done\n')
            self.finish()
            post_request = None
        elif self.method == 'GET':
            get_request = self
            if post_request:
                print 'channel id', id(post_request.channel)
                post_request.channel.resumeProducing()
            return twisted.web.server.NOT_DONE_YET

class SyncSendHttp(http.HTTPChannel):
    requestFactory = SyncSendRequest

class SyncSendHttpFactory(http.HTTPFactory):
    protocol = SyncSendHttp

if __name__ == "__main__":
    from twisted.internet import reactor
    reactor.listenTCP(8000, SyncSendHttpFactory())
    reactor.run()
