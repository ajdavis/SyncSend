# SyncSend
# (c) 2011 A. Jesse Jiryu Davis <ajdavis@cs.oberlin.edu>
# MIT license
# https://github.com/ajdavis/SyncSend
#

make_uploader = (options) ->
    new qq.FileUploader # qq.FileUploader from http://valums.com/ajax-upload/
        element: $('#file_uploader')[0]
        action: '/api/'
        template: """
            <div class="qq-uploader">
                <div class="qq-upload-drop-area"><span>Drop files here to upload</span></div>
                <div class="qq-upload-button">Upload File</div>
                <ul class="qq-upload-list"></ul>
            </div>"""
        onComplete: options.callback
        onCancel: options.cancel

class SyncSend
    constructor: ->
        $('#send_button').click ->
            $('#receive_container').fadeOut ->
                $('#send_container').fadeIn()

        $('#receive_button').click ->
            $('#send_container').fadeOut ->
                $('#receive_container').fadeIn()

        # TODO: disable submit buttons until forms are filled out
        $('#send_email').submit @submit_send_email_form
        $('#receive').submit @submit_receive_form

    submit_send_email_form: (e) =>
        $send_email_form = $ e.target
        $send_email_form.attr 'disabled', true
        email = $send_email_form.find('input[name="email"]').val()

        uploader = make_uploader
            callback: (id, fileName, responseJSON) ->
                if responseJSON
                    alert 'done'
                else
                    alert 'error'
            cancel: (id, fileName) ->
                alert 'cancel'
        $send_file_form = $('#send_file')
        $send_file_form.attr 'action', '/api/' + encodeURIComponent email
        $send_file_form.find('input[name="email"]').val email
        $send_file_form.fadeIn()

        return false
    submit_receive_form: (e) =>
        $form = $ '#receive'
        email = $form.find('input[name="email"]').val()
        if email
            window.open "/api/#{ encodeURIComponent(email) }",'Download'
        return false

new SyncSend()
