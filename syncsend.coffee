# SyncSend
# (c) 2011 A. Jesse Jiryu Davis <ajdavis@cs.oberlin.edu>
# MIT license
# https://github.com/ajdavis/SyncSend
#

config =
    use_ajax_upload: no

# options: callback, cancel (another callback), email (the email address)
make_uploader = (options) ->
    new qq.FileUploader # qq.FileUploader from http://valums.com/ajax-upload/
        element: $('#file_uploader')[0]
        action: '/api/'
        debug: true
        template: """
            <div class="qq-uploader">
                <div class="qq-upload-drop-area"><span>Drop files here to upload</span></div>
                <div class="qq-upload-button">Upload File</div>
                <ul class="qq-upload-list"></ul>
            </div>"""
        onComplete: options.callback
        onCancel: options.cancel
        params:
            email: options.email

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
        $send_file_form = $('#send_file')
        $file_input = $send_file_form.find('input[type="file"]')
        $submit_button = $send_file_form.find('input[type="submit"]')

        email = $send_email_form.find('input[name="email"]').val()
        $send_file_form.attr 'action', '/api/' + encodeURIComponent email

        if config.use_ajax_upload
            uploader = make_uploader
                email: email
                callback: (id, fileName, responseJSON) ->
                    # Nada
                cancel: (id, fileName) ->
                    # Null

            # Won't be needing the regular upload field any more
            $file_input.hide()
            $submit_button.hide()

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
