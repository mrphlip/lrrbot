function init()
{
	$('form').submit(validate);
	$('div.button.add').click(addText);
	$('div.button.remove').click(deleteText);
}
$(init);

function addText()
{
	var field = $(
		"<div>" +
			"<div class='button icon remove'></div>" +
			"<div class='input'><input type='text'></div>" +
		"</div>"
	);
	field.find('input').prop('name', $(this).data('name'));
	field.find('div.button.remove').click(deleteText);
	$(this).parent().before(field);
	$(this).closest('div.commands_list').find('div.button.remove').removeClass('disabled');
}

function deleteText()
{
	var list = $(this).closest('div.commands_list');
	var inputCount = list.find('input').length;
	if (inputCount <= 1)
		return;
	$(this).parent().remove();
	if (inputCount <= 2)
		list.find('div.button.remove').addClass('disabled');
}

function validate()
{
	return true;
	var foundAny = false;
	$('#aliases input').each(function() {
		var val = $(this).val().trim();
		if (val != "") {
			foundAny = true;
			return false;
		}
	});
	if (!foundAny) {
		alert("Commands are missing");
		return false;
	}

	foundAny = false;
	$('#responses input').each(function() {
		var val = $(this).val().trim();
		if (val != "") {
			foundAny = true;
			return false;
		}
	});
	if (!foundAny) {
		alert("Responses are missing");
		return false;
	}

	return true;
}

