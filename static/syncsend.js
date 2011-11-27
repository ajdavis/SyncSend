(function() {
  $(function() {
    var $receive_button, $receive_email, $receive_form, $sender_email, $sender_email_form, $sender_email_form_submit, $sender_file_form, config, getParameterByName, is_email, make_uploader, msg, seriouslyOnChange, showMsg, upload_action;
    config = {
      use_ajax_upload: true
    };
    $('#tabs').tabs();
    $sender_email_form = $('#sender_email_form');
    $sender_file_form = $('#sender_file_form');
    $receive_form = $('#receive_form');
    $receive_button = $('#receive_form').find('input[type="submit"]');
    $sender_email_form_submit = $sender_email_form.find('input[type="submit"]');
    if (config.use_ajax_upload) {
      $sender_file_form.find('input[type="file"]').remove();
      $sender_file_form.find('input[type="submit"]').remove();
    }
    $sender_email_form.find('input').prop('disabled', false);
    getParameterByName = function(name) {
      var regex, regexS, results;
      name = name.replace(/[\[]/, "\\\[").replace(/[\]]/, "\\\]");
      regexS = "[\\?&]" + name + "=([^&#]*)";
      regex = new RegExp(regexS);
      results = regex.exec(window.location.href);
      if (results === null) {
        return "";
      } else {
        return decodeURIComponent(results[1].replace(/\+/g, " "));
      }
    };
    is_email = function(email) {
      var emailPattern;
      emailPattern = /^[a-zA-Z0-9._-]+(\+[a-zA-Z0-9._-]+)?@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,4}$/;
      return emailPattern.test(email);
    };
    showMsg = function(msg) {
      var $msg;
      $msg = $('#msg');
      return $msg.html(msg).slideDown(function() {
        return setTimeout((function() {
          return $msg.slideUp();
        }), 4000);
      });
    };
    seriouslyOnChange = function($input, callback) {
      var val;
      val = $input.val();
      return (function() {
        var timer;
        return timer = setInterval((function() {
          var newVal;
          newVal = $input.val();
          if (newVal !== val) {
            val = newVal;
            if (callback(val)) {
              return clearInterval(timer);
            }
          }
        }), 100);
      })();
    };
    upload_action = function(email) {
      return "/api/" + (encodeURIComponent(email));
    };
    make_uploader = function(options) {
      return new qq.FileUploader({
        element: $('#file_uploader')[0],
        action: upload_action(options.email),
        debug: true,
        template: "<div class=\"qq-uploader\">\n    <div class=\"qq-upload-drop-area\"><span>Drop files here to upload</span></div>\n    <div class=\"qq-upload-button\">Upload File</div>\n    <ul class=\"qq-upload-list\"></ul>\n</div>",
        onSubmit: options.submit || function() {},
        onComplete: options.complete || function() {},
        onCancel: options.cancel || function() {}
      });
    };
    msg = getParameterByName('msg');
    if (msg) {
      showMsg(msg);
    }
    window.location.hash = '';
    $sender_email = $('#sender_email');
    seriouslyOnChange($sender_email, function() {
      var email, email_valid;
      email = $sender_email.val();
      email_valid = is_email(email);
      $sender_email_form_submit.prop('disabled', !email_valid);
      return false;
    });
    $sender_email_form.submit(function() {
      var uploader;
      $sender_email_form.find('input').prop('disabled', true);
      $sender_file_form.fadeIn();
      if (config.use_ajax_upload) {
        uploader = make_uploader({
          email: $sender_email.val(),
          complete: function(id, fileName, responseJSON) {
            showMsg("Your upload is complete");
            return $send_file_form.fadeOut();
          }
        });
      } else {
        $sender_file_form.find('input[type="file,submit"]').hide();
        $send_file_form.attr('action', upload_action(email));
        uploader = null;
      }
      return false;
    });
    $sender_file_form.find('input[name="cancel"]').click(function() {
      $sender_email_form.find('input').prop('disabled', false);
      return $sender_file_form.fadeOut();
    });
    $receive_email = $receive_form.find('input[name="email"]');
    seriouslyOnChange($receive_email, function() {
      var email, email_valid;
      email = $receive_email.val();
      email_valid = is_email(email);
      $receive_button[email_valid ? 'fadeIn' : 'fadeOut']();
      return email_valid;
    });
    $receive_form.submit(function() {
      var email;
      email = $receive_form.find('input[name="email"]').val();
      if (email) {
        window.open("/api/" + (encodeURIComponent(email)), 'Download');
      }
      return false;
    });
    $receive_email.val('');
    $sender_email.val('');
    return $sender_file_form.find('input[type="file"]').val('');
  });
}).call(this);
