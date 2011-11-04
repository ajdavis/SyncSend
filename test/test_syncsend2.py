import subprocess
import multiprocessing
import os
import unittest
import urllib2
from tempfile import NamedTemporaryFile
import time
import json
import signal

from formdata import encode_multipart_formdata

def kill(process):
    os.kill(process.pid, signal.SIGKILL)

class SyncSendTransferTest(unittest.TestCase):
    def _test_transfer(self, postdata, key, send_first, content_type, expected_value=None):
        """
        Test sending and receiving some data
        @param postdata:        The request body
        @param key:             The unique key, e.g. the sender's email address
        @param send_first:      If True, start sending before receiving, otherwise the opposite
        @param content_type:    POST request's content-type
        @param expected_value:  If not None, the expected data to download (otherwise we expect postdata)
        """
        print 'postdata:\n%s' % repr(postdata)
        print 'length', len(postdata)

        start_server = os.environ.get('SYNCSEND_TEST_NO_SERVER', '').upper() != 'TRUE'

        path = 'api/' + key
        self.portno = 8000
        url = self._get_url(path, self.portno)

        manager = multiprocessing.Manager()
        shared = manager.dict()

        # === START THE SERVER ===
        # It'd be more convenient to use multiprocessing for this subprocess too, but I read
        # on the Internet that Twisted is incompatible with multiprocessing because they
        # step on each other's SIGCHLD handlers. I've found this to be true by experiment,
        # though I don't know the details.
        thisdir = os.path.dirname(__file__)
        if start_server:
            server = subprocess.Popen(
                ['/Users/emptysquare/python/syncsend/bin/python', 'syncsend.py', str(self.portno)],
                cwd=os.path.normpath(os.path.join(thisdir, '..')),
            )
            time.sleep(0.5) # Make sure the server starts up
            print 'Server pid: ', server.pid
        else:
            server = None

        def post_fn(shared):
            request = urllib2.Request(url=url, data=postdata, headers={ 'Content-Type': content_type })
            post_result = urllib2.urlopen(request).read()
            print 'post_fn() got:', post_result
            shared['post_result'] = post_result
        post = multiprocessing.Process(target=post_fn, args=(shared, ))

        def get_fn(shared):
            get_result = urllib2.urlopen(url=url).read()
            print 'get_fn() got length %d: %s' % (len(get_result), str(get_result)[:1000])
            shared['get_result'] = get_result
        get = multiprocessing.Process(target=get_fn, args=(shared, ))

        if send_first:
            post.start()
            print 'POST: pid', post.pid
            time.sleep(0.25)
            get.start()
            print 'GET: pid', get.pid
        else:
            get.start()
            print 'GET: pid', get.pid
            time.sleep(0.25)
            post.start()
            print 'POST: pid', post.pid

        # Wait for the sender and receiver to complete
        post.join(timeout=5)
        get.join(timeout=5)

        # The server will run indefinitely unless killed
        if start_server: kill(server)

        # post and get processes should be gone by now; make sure (we'll assert later
        # that they terminated on their own, to catch problems in the test harness)
        for name in 'post', 'get':
            p = locals()[name]
            if p.is_alive():
                print 'killing', name, 'request'
                kill(p)

        self.assert_('get_result' in shared, "GET request did not complete")

        def clip_data(data):
            """
            Clip long data, displaying only the beginning and end
            """
            length = 40
            r = repr(data)
            if len(r) <= length:
                return r

            return '%s...%s' % (r[:length/2], r[-length/2:])

        ev = postdata if expected_value is None else expected_value
        clipped_ev = clip_data(ev)
        clipped_result = clip_data(shared['get_result'])
        self.assertEqual(
            ev,
            shared['get_result'],
            "Downloaded wrong data\nSent (%9d):     %s\nReceived (%9d): %s" % (
                len(ev), clip_data(ev), len(shared['get_result']), clipped_result,
            )
        )

        self.assertEqual({ "success": 1}, json.loads(shared['post_result']))

        for name in 'post', 'get':
            p = locals()[name]
            self.assertEquals(0, p.exitcode, '%s had exit code %s' % (name, p.exitcode))

    def _get_url(self, path, portno):
        return "http://localhost:%d/%s" % (self.portno, path)

    def _test_xhr_upload(self, data_length, send_first):
        print 'XHR  length: ', data_length, 'send_first: ', send_first
        postdata = '0' * data_length
        self._test_transfer(postdata, 'fake_email_address', send_first, 'application/octet-stream')

    def _test_multipart_form_upload(self, data_length, send_first):
        print 'FORM length: ', data_length, 'send_first: ', send_first
        with NamedTemporaryFile() as tmp:
            tmp.write('a' * data_length)
            tmp.seek(0, 0)

            content_type, postdata = encode_multipart_formdata(
                fields=[], # TODO: throw some fields into the mix, both before and after file
                files=[('fake_name', 'fake_filename', tmp.name)]
            )

            tmp.seek(0, 0)
            self._test_transfer(postdata, 'fake_email_address', send_first, content_type, expected_value=tmp.read())
#
#for data_length in range(0, 18):
#    for send_first in (True, False):
#        # Close over the data_length and send_first values
#        def immediate(data_length, send_first):
#            fname = 'test_xhr_%02d_bytes_%s_first' % (
#                data_length, 'send' if send_first else 'receive'
#            )
#
#            setattr(SyncSendTransferTest, fname, lambda self: self._test_xhr_upload(data_length, send_first))
#        immediate(data_length, send_first)

for data_length, length_name in [
#    (0, 'zero'),
    (1024, '1kb'),
#    (1024**2, '1MB'),
#    (1024**3, '1GB'),
]:
    for send_first in (True, ):
#    for send_first in (True, False):
        # Close over the data_length and send_first values
        def immediate(data_length, send_first):
            fname = 'test_multipart_form_%s_%s_first' % (
                length_name, 'send' if send_first else 'receive'
            )

            setattr(SyncSendTransferTest, fname, lambda self: self._test_multipart_form_upload(data_length, send_first))
        immediate(data_length, send_first)


if __name__ == '__main__':
    import unittest
    unittest.main(verbosity=2)
