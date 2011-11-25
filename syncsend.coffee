# SyncSend
# (c) 2011 A. Jesse Jiryu Davis <ajdavis@cs.oberlin.edu>
# MIT license
# https://github.com/ajdavis/SyncSend
#

$ ->
    ######## CONFIGURATION ########
    config =
        use_ajax_upload: true

    # Set up the tab interface
    $('#tabs').tabs()

    # Cache some jQuery objects
    $sender_email_form = $('#sender_email_form')
    $sender_file_form = $('#sender_file_form')
    $receive_form = $('#receive_form')
    $receive_button = $('#receive_form').find('input[type="submit"]')
    $sender_email_form_submit = $sender_email_form.find('input[type="submit"]')

    ######## CONFIGURATION ########
    if config.use_ajax_upload
        $sender_file_form.find('input[type="file"]').remove()
        $sender_file_form.find('input[type="submit"]').remove()

    $sender_email_form.find('input').prop 'disabled', false

    ######## FUNCTIONS ########

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
    # $input: a jQuerified input elem
    # callback: called on change. return true to clear handler
    # TODO: way to stop the timer
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

    ######## SHOW USER MESSAGE ########
    msg = getParameterByName 'msg'
    showMsg(msg) if msg
    window.location.hash = ''

    ######## SENDER EVENT HANDLERS ########

    # Enable file upload when user has entered email address
    $sender_email = $('#sender_email')
    seriouslyOnChange $sender_email, ->
        email = $sender_email.val()
        email_valid = is_email email
        $sender_email_form_submit.prop 'disabled', not email_valid
        false # don't clear callback

    $sender_email_form.submit ->
        $sender_email_form.find('input').prop 'disabled', true
        $sender_file_form.fadeIn()

        if config.use_ajax_upload
            uploader = make_uploader
                email: $sender_email.val()
                complete: (id, fileName, responseJSON) ->
                    showMsg "Your upload is complete"
                    $send_file_form.fadeOut()
        else
            $sender_file_form.find('input[type="file,submit"]').hide()
            $send_file_form.attr 'action', upload_action email
            uploader = null
        return false

    $sender_file_form.find('input[name="cancel"]').click ->
        $sender_email_form.find('input').prop 'disabled', false
        $sender_file_form.fadeOut()

    $receive_email = $receive_form.find('input[name="email"]')
    seriouslyOnChange $receive_email, ->
        email = $receive_email.val()
        email_valid = is_email email
        $receive_button[if email_valid then 'fadeIn' else 'fadeOut']()
        return email_valid

    $receive_form.submit ->
        email = $receive_form.find('input[name="email"]').val()
        if email
            window.open "/api/#{ encodeURIComponent(email) }",'Download'
        return false

    # Don't let the browser pre-enter form fields
    $receive_email.val('')
    $sender_email.val('')
    $sender_file_form.find('input[type="file"]').val('')
