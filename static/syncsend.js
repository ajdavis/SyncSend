(function() {
  var SyncSend, make_uploader;
  var __bind = function(fn, me){ return function(){ return fn.apply(me, arguments); }; };
  make_uploader = function(options) {
    return new qq.FileUploader({
      element: $('#file_uploader')[0],
      action: '/api/',
      template: "<div class=\"qq-uploader\">\n    <div class=\"qq-upload-drop-area\"><span>Drop files here to upload</span></div>\n    <div class=\"qq-upload-button\">Upload File</div>\n    <ul class=\"qq-upload-list\"></ul>\n</div>",
      onComplete: options.callback,
      onCancel: options.cancel
    });
  };
  SyncSend = (function() {
    function SyncSend() {
      this.submit_receive_form = __bind(this.submit_receive_form, this);;
      this.submit_send_email_form = __bind(this.submit_send_email_form, this);;      $('#send_button').click(function() {
        return $('#receive_container').fadeOut(function() {
          return $('#send_container').fadeIn();
        });
      });
      $('#receive_button').click(function() {
        return $('#send_container').fadeOut(function() {
          return $('#receive_container').fadeIn();
        });
      });
      $('#send_email').submit(this.submit_send_email_form);
      $('#receive').submit(this.submit_receive_form);
    }
    SyncSend.prototype.submit_send_email_form = function(e) {
      var $send_email_form, $send_file_form, email, uploader;
      $send_email_form = $(e.target);
      $send_email_form.attr('disabled', true);
      email = $send_email_form.find('input[name="email"]').val();
      uploader = make_uploader({
        callback: function(id, fileName, responseJSON) {
          if (responseJSON) {
            return alert('done');
          } else {
            return alert('error');
          }
        },
        cancel: function(id, fileName) {
          return alert('cancel');
        }
      });
      $send_file_form = $('#send_file');
      $send_file_form.attr('action', '/api/' + encodeURIComponent(email));
      $send_file_form.find('input[name="email"]').val(email);
      $send_file_form.fadeIn();
      return false;
    };
    SyncSend.prototype.submit_receive_form = function(e) {
      var $form, email;
      $form = $('#receive');
      email = $form.find('input[name="email"]').val();
      if (email) {
        window.open("/api/" + (encodeURIComponent(email)), 'Download');
      }
      return false;
    };
    return SyncSend;
  })();
  new SyncSend();
}).call(this);
