/**
 * Created by ftrauts on 22.06.16.
 */
$(document).ready(function() {
    var id = $('#id_revisions').attr('id')


    $('#id_revisions').hide()
    $('label[for="' + id + '"]').hide();

    $('#arguments_form input').on('change', function() {
        var val = $('input[name=execution]:checked', '#arguments_form').val();
        if (val == 'rev') {
            $('#id_revisions').show()
            $('label[for="' + id + '"]').show();

        } else {
            $('#id_revisions').hide()
            $('label[for="' + id + '"]').hide();
        }

    });

});

