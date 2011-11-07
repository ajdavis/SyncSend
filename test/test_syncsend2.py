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

# Byte-lengths of files to test
lengths = [
    (0, 'zero'),
    (1, '1b'),
    #    (2, '2b'),
    #    (3, '3b'),
    (15, '15b'),
    #    (16, '16b'),
    (17, '17b'),
    #    (1024, '1kb'),
    #    (10 * 1024, '10kb'),
    (63 * 1024, '63kb'),
    #    (64 * 1024, '64kb'),
    (65 * 1024, '65kb'),
    #    (1024**2, '1MB'),
    #    ((1024**3)/2, '500MB'),
]

def kill(process):
    os.kill(process.pid, signal.SIGKILL)

class SyncSendTransferTest(unittest.TestCase):
    def _test_transfer(
        self,
        postdata,
        key,
        send_first,
        content_type,
        expected_value=None,
        n_transfers=1,
        expected_content_length=None,
    ):
        """
        Test sending and receiving some data
        @param postdata:                The request body
        @param key:                     The unique key, e.g. the sender's email address
        @param send_first:              If True, start sending before receiving, otherwise the opposite
        @param content_type:            POST request's content-type
        @param expected_value:          If not None, the expected data to download (otherwise we expect postdata)
        @param n_transfers:             Number of simultaneous transfers
        @param expected_content_length: If not -1, check the response's content-length
        """
        start_server = os.environ.get('SYNCSEND_TEST_NO_SERVER', '').upper() != 'TRUE'

        path = 'api/' + key
        self.portno = 8000
        url = self._get_url(path, self.portno)

        manager = multiprocessing.Manager()
        shareds = [manager.dict() for i in range(n_transfers)]
        n_children_running = manager.Value('i', n_transfers * 2) # an int
        n_children_running_lock = manager.Lock()
        children_complete = manager.Condition()

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
        else:
            server = None

        def child_complete():
            with n_children_running_lock:
                n_children_running.value -= 1
                if n_children_running.value == 0:
                    with children_complete:
                        children_complete.notify()

        def post_fn(i):
            request = urllib2.Request(url=url + str(i), data=postdata, headers={ 'Content-Type': content_type })
            shareds[i]['post_result'] = urllib2.urlopen(request).read()
            child_complete()
        posts = [multiprocessing.Process(target=post_fn, args=(i, )) for i in range(n_transfers)]

        def get_fn(i):
            get_result = urllib2.urlopen(url=url + str(i))
            shareds[i]['get_result'] = get_result.read()
            shareds[i]['content_length'] = get_result.headers.getheader('Content-Length')
            child_complete()
        gets = [multiprocessing.Process(target=get_fn, args=(i, )) for i in range(n_transfers)]

        if send_first:
            [p.start() for p in posts]
            time.sleep(0.1)
            [g.start() for g in gets]
        else:
            [g.start() for g in gets]
            time.sleep(0.1)
            [p.start() for p in posts]

        # Wait for the senders and receivers to complete - give more time for more transferring
        timeout = 10 + n_transfers + (len(postdata) * n_transfers) / (1024**2)
        print 'waiting up to', timeout, 'seconds'
        with children_complete:
            children_complete.wait(timeout=timeout)

        # All the child functions have exited, but give the processes themselves a second to die
        [g.join(timeout=1) for g in gets]
        [p.join(timeout=1) for p in posts]

        # The server will run indefinitely unless killed
        if start_server: kill(server)

        # post and get processes should be gone by now; make sure (we'll assert later
        # that they terminated on their own, to catch problems in the test harness)
        for name in 'posts', 'gets':
            processes = locals()[name]
            for i, p in enumerate(processes):
                if p.is_alive():
                    print 'killing', name, 'request number', i
                    kill(p)

        for i in range(n_transfers):
            self.assert_('get_result' in shareds[i], "GET request number %s did not complete" % i)

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
        for i in range(n_transfers):
            result = shareds[i]['get_result']
            clipped_result = clip_data(result)
            self.assertEqual(
                ev,
                result,
                "Downloaded wrong data\nSent (%9d):     %s\nReceived (%9d): %s" % (
                    len(ev), clip_data(ev), len(result), clipped_result,
                )
            )

            if expected_content_length is not None:
                content_length = shareds[i].get('content_length')
                self.assert_(content_length is not None, "No content-length in GET response")
                self.assertEqual(
                    expected_content_length,
                    int(content_length),
                    'Wrong content-length'
                )

        # SyncSendUploadRequests should return the JSON "{ success: 1 }" for XMLHTTPRequest-style uploads
        if not content_type.startswith('multipart/form-data'):
            for i in range(n_transfers):
                self.assertEqual({ "success": 1 }, json.loads(shareds[i]['post_result']))

        for name in 'posts', 'gets':
            processes = locals()[name]
            for i, p in enumerate(processes):
                self.assertEquals(0, p.exitcode, '%s number %s had exit code %s' % (name, i, p.exitcode))

    def _get_url(self, path, portno):
        return "http://localhost:%d/%s" % (self.portno, path)

class SyncSendXHRTest(SyncSendTransferTest):
    def _test_xhr_upload(self, data_length, send_first):
        postdata = '0' * data_length
        self._test_transfer(
            postdata,
            'fake_email_address',
            send_first,
            'application/octet-stream',
            expected_content_length=data_length,
        )

    def test_2_xhr_transfers(self):
        postdata = '0' * 1024
        self._test_transfer(postdata, 'fake_email_address', send_first, 'application/octet-stream', n_transfers=2)

    def test_20_xhr_transfers(self):
        postdata = '0' * 2 * 1024**2
        self._test_transfer(postdata, 'fake_email_address', send_first, 'application/octet-stream', n_transfers=20)

# Generate some XMLHTTPRequest file-upload tests for all the file sizes
for data_length, length_name in lengths:
    for send_first in (True,):# False):
        # Close over the data_length and send_first values
        def immediate(data_length, send_first):
            fname = 'test_xhr_%02d_bytes_%s_first' % (
                data_length, 'send' if send_first else 'receive'
                )

            def f(self):
                self._test_xhr_upload(data_length, send_first)
            f.__name__ = fname
            setattr(SyncSendXHRTest, fname, f)
        immediate(data_length, send_first)

class SyncSendMultipartFormTest(SyncSendTransferTest):
    def _test_multipart_form_upload(self, data_length, send_first):
        with NamedTemporaryFile() as tmp:
            tmp.write('a' * data_length)
            tmp.seek(0, 0)

            content_type, postdata = encode_multipart_formdata(
                fields=[('field1', 'foobar'), ('fake_name', 'fake_filename', tmp.name), ('field2', 'fuzzbutt')]
            )

            tmp.seek(0, 0)
            self._test_transfer(postdata, 'fake_email_address', send_first, content_type, expected_value=tmp.read())

    def test_multipart_form_with_fields(self):
        for send_first in (True, False):
            with NamedTemporaryFile() as tmp:
                tmp.write('a' * 1024)
                tmp.seek(0, 0)

                for content_type, postdata in [
                    encode_multipart_formdata(
                        fields=[('field1', 'foobar'), ('fake_name', 'fake_filename', tmp.name), ('field2', 'fuzzbutt')]
                    ),
                    encode_multipart_formdata(
                        fields=[('field1', 'foobar'), ('fake_name', 'fake_filename', tmp.name)]
                    ),
                    encode_multipart_formdata(
                        fields=[('fake_name', 'fake_filename', tmp.name), ('field2', 'fuzzbutt')]
                    ),
                    encode_multipart_formdata(
                        fields=[('fake_name', 'fake_filename', tmp.name)]
                    ),
                ]:
                    tmp.seek(0, 0)
                    self._test_transfer(postdata, 'fake_email_address', send_first, content_type, expected_value=tmp.read())

# Generate some mlutipart-form file-upload tests for all the file sizes
for data_length, length_name in lengths:
    for send_first in (True, False):
        # Close over the data_length and send_first values
        def immediate(data_length, send_first):
            fname = 'test_multipart_form_%s_%s_first' % (
                length_name, 'send' if send_first else 'receive'
            )

            def f(self):
                self._test_multipart_form_upload(data_length, send_first)
            f.__name__ = fname
            setattr(SyncSendMultipartFormTest, fname, f)
        immediate(data_length, send_first)


if __name__ == '__main__':
    import unittest
    unittest.main(verbosity=2)
