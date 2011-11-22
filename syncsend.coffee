# SyncSend
# (c) 2011 A. Jesse Jiryu Davis <ajdavis@cs.oberlin.edu>
# MIT license
# https://github.com/ajdavis/SyncSend
#

$ ->
    # Do some jQuery UI stuff
    $('#tabs').tabs()

    # From http://stackoverflow.com/questions/901115/get-query-string-values-in-javascript
    getParameterByName = (name) ->
        name = name.replace(/[\[]/, "\\\[").replace(/[\]]/, "\\\]")
        regexS = "[\\?&]" + name + "=([^&#]*)"
        regex = new RegExp(regexS)
        results = regex.exec(window.location.href)
        if(results == null)
            return ""
        else
            return decodeURIComponent(results[1].replace(/\+/g, " "))

    is_email = (email) ->
        emailPattern = /^[a-zA-Z0-9._-]+(\+[a-zA-Z0-9._-]+)?@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,4}$/
        return emailPattern.test(email)

    # Maybe show the user a message
    showMsg = (msg) ->
        $msg = $('#msg')
        $msg.html(msg).slideDown -> setTimeout((
            -> $msg.slideUp()
        ), 4000)

    # Detect change in a field by any means necessary
    seriouslyOnChange = ($input, callback) ->
        val = $input.val()
        do ->
            timer = setInterval((->
                newVal = $input.val()
                if newVal isnt val
                    val = newVal
                    if callback val
                        clearInterval timer
            ), 100)

    msg = getParameterByName 'msg'
    showMsg(msg) if msg
    window.location.hash = ''

    config =
        use_ajax_upload: true

    upload_action = (email) -> "/api/#{ encodeURIComponent(email) }"

    # options:
    # email (the email address)
    # submit(id, fileName): called on submit (return false to cancel)
    # complete(id, fileName, responseJSON): completion callback
    # cancel(id, fileName): called on cancel
    make_uploader = (options) ->
        new qq.FileUploader # qq.FileUploader from http://valums.com/ajax-upload/
            element: $('#file_uploader')[0]
            action: upload_action options.email
            debug: true
            template: """
                <div class="qq-uploader">
                    <div class="qq-upload-drop-area"><span>Drop files here to upload</span></div>
                    <div class="qq-upload-button">Upload File</div>
                    <ul class="qq-upload-list"></ul>
                </div>"""
            onSubmit: options.submit or ->
            onComplete: options.complete or ->
            onCancel: options.cancel or ->

    class SyncSend
        constructor: ->
            # Cache some jQuery objects
            @$send_file_form = $('#send_file')
            @$file_input = @$send_file_form.find('input[type="file"]')
            @$submit_button = @$send_file_form.find('input[type="submit"]')
            @$send_email_email = $('#send_email_email')
            @$receive = $('#receive')
            @$receive_button = @$receive.find('input[type="submit"]').hide()

            $('#send_email').submit -> false

            if config.use_ajax_upload
                # Won't be needing the regular upload field any more
                @$file_input.hide()
                @$submit_button.hide()

            # Enable file upload when user has entered email address
            show_upload = no

            $receive_email = $('#receive_email')
            seriouslyOnChange $receive_email, =>
                email = $receive_email.val()
                email_valid = is_email email
                @$receive_button[if email_valid then 'fadeIn' else 'fadeOut']()
                return email_valid

            seriouslyOnChange @$send_email_email, =>
                email = @$send_email_email.val()
                email_valid = is_email email
                if email_valid and not show_upload
                    show_upload = yes
                    $('#send_file').fadeIn()
                    if config.use_ajax_upload
                        @uploader = make_uploader
                            email: email
                            complete: (id, fileName, responseJSON) ->
                                showMsg "Your upload is complete"
                                @$send_file_form.fadeOut()
                    else
                        @$send_file_form.attr 'action', upload_action email
                        @$file_input.show()
                    return true # clear change handler
                else if not email_valid and show_upload
                    show_upload = no
                    $('#send_file').fadeOut ->
                        $('#file_uploader').html('')
                    @uploader = null
                return false # don't clear change handler

            $('#receive').submit @submit_receive_form

            # Don't let the browser pre-enter form fields
            $receive_email.val('')
            @$send_email_email.val('')
            @$file_input.val('')
        submit_receive_form: (e) =>
            $form = $ '#receive'
            email = $form.find('input[name="email"]').val()
            if email
                window.open "/api/#{ encodeURIComponent(email) }",'Download'
            return false

    new SyncSend()
