import mimetypes

def get_content_type(filename):
    return mimetypes.guess_type(filename)[0] or 'application/octet-stream'

# Adapted from http://code.activestate.com/recipes/146306-http-client-to-post-using-multipartform-data/
def encode_multipart_formdata(fields):
    """
    fields is a sequence of (name, value) elements for regular form fields or
    (name, filename, value) elements for data to be uploaded as files.
    Return (content_type, body) ready for httplib.HTTP instance
    """
    BOUNDARY = '----------ThIs_Is_tHe_bouNdaRY_$'
    CRLF = '\r\n'
    L = []
    for tup in fields:
        if len(tup) == 2:
            key, value = tup
            L.append('--' + BOUNDARY)
            L.append('Content-Disposition: form-data; name="%s"' % key)
            L.append('')
            L.append(value)
        elif len(tup) == 3:
            key, filename, value = tup
            L.append('--' + BOUNDARY)
            L.append('Content-Disposition: form-data; name="%s"; filename="%s"' % (key, filename))
            L.append('Content-Type: %s' % get_content_type(filename))
            L.append('')
            with open(value) as f:
                L.append(f.read())
        else:
            raise ValueError, "field %s should have had 2 or 3 elements" % repr(tup)
    L.append('--' + BOUNDARY + '--')
    L.append('')
    body = CRLF.join(L)
    content_type = 'multipart/form-data; boundary=%s' % BOUNDARY
    return content_type, body
