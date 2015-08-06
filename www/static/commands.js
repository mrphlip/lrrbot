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
			"<td class='access'>" +
				"<select>" +
					"<option value='any'>Anyone</option>" +
					"<option value='sub'>Subscribers</option>" +
					"<option value='mod'>Moderators</option>" +
				"</select>" +
			"</td>" +
			"<td class='button'>" +
				"<button class='del'>Del</button>" +
			"</td>" +
		"</tr>"
	);
	if (jQuery("table.commands").data('mode') === "explanations")
		row.find('.access select').val('mod');
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
		if (val.length > 450) {
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
		'data': "data=" + encodeURIComponent(data) + "&mode=" + encodeURIComponent(mode) + "&_csrf_token=" + encodeURIComponent(window.csrf_token) + "&key=" + window.command_key,
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
		var access = row.find('td.access select').val();
		row.find('td.command input').each(function() {
			data[$(this).val()] = {
				'response': responses,
				'access': access
			};
		});
	});
	return JSON.stringify(data);
}

function saveSuccess(data)
{
	window.csrf_token = data["csrf_token"];
	window.command_key = data["new_key"];
	$('div.loading').hide();
	$('button.save').show();
	alert("Saved");
}

function saveError(data)
{
	$('div.loading').hide();
	$('button.save').show();
	if (typeof data.responseJSON != "undefined") {
		window.csrf_token = data.responseJSON["csrf_token"];
		alert("Error saving commands: " + data.responseJSON["message"]);
	} else {
		alert("Error saving commands");
	}
}
