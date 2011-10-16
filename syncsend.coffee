# SyncSend
# (c) 2011 A. Jesse Jiryu Davis <ajdavis@cs.oberlin.edu>
# MIT license
# https://github.com/ajdavis/SyncSend

SocketIOFileUploader = (o) ->
    # call parent constructor
    qq.FileUploader.apply this, arguments
    
    input = @_inputs[id]
    
    if not input
        throw new Error 'file with passed id was not added, or already uploaded or cancelled'

    fileName = @getName id


class SyncSend
    constructor: ->
        $('#send_button').click ->
            $('#receive_container').fadeOut ->
                $('#send_container').fadeIn()

        $('#receive_button').click ->
            $('#send_container').fadeOut ->
                $('#receive_container').fadeIn()

        $('#send_email').submit @submit_send_email_form
        $('#receive').submit @submit_receive_form

    submit_send_email_form: (e) =>
        $send_email_form = $ e.target
        $send_email_form.attr 'disabled', true
        email = $send_email_form.find('input[name="email"]').val()

        $send_file_form = $('#send_file')
        $send_file_form.attr 'action', 'http://localhost:8000/api/' + encodeURIComponent email
        $send_file_form.fadeIn()

        return false
    submit_receive_form: (e) =>
        return false

new SyncSend()
