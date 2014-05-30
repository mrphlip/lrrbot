function init()
{
	$('button.save').click(save);
	$('button.add').click(addRow);
	$('button.del').click(deleteRow);
	$('div.button.add').click(addText);
	$('div.button.remove').click(deleteText);

	fixRows();
}
$(init);

function addRow()
{
	var row = $(
		"<tr>" +
			"<td class='command'>" +
				"<div>" +
					"<div class='button remove disabled'></div>" +
					"<div class='input'><input type='text'></div>" +
				"</div>" +
				"<div>" +
					"<div class='button add'></div>" +
				"</div>" +
			"</td>" +
			"<td class='response'>" +
				"<div>" +
					"<div class='button remove disabled'></div>" +
					"<div class='input'><input type='text'></div>" +
				"</div>" +
				"<div>" +
					"<div class='button add'></div>" +
				"</div>" +
			"</td>" +
			"<td class='button'>" +
				"<button class='del'>Del</button>" +
			"</td>" +
		"</tr>"
	);
	row.find('button.del').click(deleteRow);
	row.find('div.button.add').click(addText);
	row.find('div.button.remove').click(deleteText);
	$('table.commands tbody').prepend(row);
	fixRows();
}

function deleteRow()
{
	var row = $(this).closest('tr');
	var label = row.find('td.command input').eq(0).val();
	if (!confirm("Remove response for !" + label + "?"))
		return;
	row.remove();
	fixRows();
}

function fixRows()
{
	var alternate = false;
	$('table.commands tbody tr').each(function() {
		alternate = !alternate;
		$(this).removeClass("odd even").addClass(alternate ? "odd" : "even");
	});
}

function addText()
{
	var field = $(
		"<div>" +
			"<div class='button remove'></div>" +
			"<div class='input'><input type='text'></div>" +
		"</div>"
	);
	field.find('div.button.remove').click(deleteText);
	$(this).parent().before(field);
	$(this).closest('td').find('div.button.remove').removeClass('disabled');
}

function deleteText()
{
	var td = $(this).closest('td');
	var inputCount = td.find('input').length;
	if (inputCount <= 1)
		return;
	$(this).parent().remove();
	if (inputCount <= 2)
		td.find('div.button.remove').addClass('disabled');
}

function save()
{
	// Do some sanity checks
	var foundError = false;
	$('input').removeClass("error");
	$('td.command input').each(function() {
		var val = $(this).val();
		if (val == "") {
			$(this).focus().addClass("error");
			alert("Command is blank");
			foundError = true;
			return false;
		}
		else if (val.indexOf(" ") >= 0) {
			$(this).focus().addClass("error");
			alert("Command must be a single word");
			foundError = true;
			return false;
		}
	});
	if (foundError) return;
	$('td.response input').each(function() {
		var val = $(this).val();
		if (val == "") {
			$(this).focus().addClass("error");
			alert("Response is blank");
			foundError = true;
			return false;
		}
		if (val.length() > 450) {
			$(this).focus().addClass("error");
			alert("Response is too long");
			foundError = true;
			return false;
		}
	});
	if (foundError) return;
	var mode = jQuery("table.commands").data('mode');
	// Send the data up to the server
	$('div.loading').show();
	$('button.save').hide();
	var data = getAsJSON();
	$.ajax({
		'type': 'POST',
		'url': "commands/submit",
		'data': "data=" + encodeURIComponent(data) + "&mode=" + encodeURIComponent(mode),
		'dataType': 'json',
		'async': true,
		'cache': false,
		'success': saveSuccess,
		'error': saveError
	})
}

function getAsJSON()
{
	var data = {};
	$('table.commands tbody tr').each(function() {
		var row = $(this);
		var responses = [];
		row.find('td.response input').each(function() {
			responses.push($(this).val());
		});
		if (responses.length == 1)
			responses = responses[0];
		row.find('td.command input').each(function() {
			data[$(this).val()] = responses;
		});
	});
	return JSON.stringify(data);
}

function saveSuccess()
{
	$('div.loading').hide();
	$('button.save').show();
	alert("Saved");
}

function saveError()
{
	$('div.loading').hide();
	$('button.save').show();
	alert("Error saving commands");
}
