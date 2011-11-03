import subprocess
import os
import unittest
from tempfile import NamedTemporaryFile

from twisted.internet import reactor
from twisted.web import client

from formdata import encode_multipart_formdata
import syncsend

class SyncSendTransferTest(unittest.TestCase):
    def testMultipartFormPOST(self):
        tmp = NamedTemporaryFile()
        tmp.write('asdf')
        tmp.seek(0, 0)

        content_type, postdata = encode_multipart_formdata(
            fields=[],
            files=[('fake_name', 'fake_filename', tmp.name)]
        )

#        print postdata
        path = 'api/fake_email_address_here'

        # Set up the server
#        self.port = reactor.listenTCP(8000, syncsend.SyncSendHttpFactory(), interface="127.0.0.1")
#        self.portno = self.port.getHost().port
        self.portno = 8000

        subp = subprocess.Popen(
            shell=True,
            args=['python ../syncsend.py'],
        )
        url = self.get_url(path, self.portno)

        # Set up the client to DOWNLOAD the file
        #client.getPage(url)

        # Set up the client to UPLOAD the file
        post_factory = client.HTTPClientFactory(
            url=url,
            method='POST',
            postdata=postdata,
            headers={
                'Content-Type': content_type,
            }
        )

        def callback(subp):
            print 'callback'
            subp.terminate()


        def error(failure, subp):
            print 'error: %s' % failure
            subp.terminate()

        post_factory.deferred.addCallback(callback, subp).addErrback(error, subp)

        connector = reactor.connectTCP('127.0.0.1', self.portno, post_factory)
        #.addErrback(error).addCallback(callback)

        reactor.run()
    def get_url(self, path, portno):
        return "http://localhost:%d/%s" % (self.portno, path)

if __name__ == '__main__':
    import unittest
    unittest.main(verbosity=2)
