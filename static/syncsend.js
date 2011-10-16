(function() {
  var SocketIOFileUploader, SyncSend;
  var __bind = function(fn, me){ return function(){ return fn.apply(me, arguments); }; };
  SocketIOFileUploader = function(o) {
    var fileName, input;
    qq.FileUploader.apply(this, arguments);
    input = this._inputs[id];
    if (!input) {
      throw new Error('file with passed id was not added, or already uploaded or cancelled');
    }
    return fileName = this.getName(id);
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
      var $send_email_form, $send_file_form, email;
      $send_email_form = $(e.target);
      $send_email_form.attr('disabled', true);
      email = $send_email_form.find('input[name="email"]').val();
      $send_file_form = $('#send_file');
      $send_file_form.attr('action', 'http://localhost:8000/api/' + encodeURIComponent(email));
      $send_file_form.fadeIn();
      return false;
    };
    SyncSend.prototype.submit_receive_form = function(e) {
      return false;
    };
    return SyncSend;
  })();
  new SyncSend();
}).call(this);
