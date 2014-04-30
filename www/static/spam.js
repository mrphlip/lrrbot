function init()
{
	$('button.save').click(save);
	$('button.test').click(test);
	$('div.button.add').click(addRow);
	$('div.button.remove').click(deleteRow);

	fixRows();
}
$(init);

function addRow()
{
	var row = $(
		"<tr>" +
			"<td class='action'>" +
				"<div class='button remove'></div>" +
			"</td>" +
			"<td class='re'>" +
				"<input type='text'>" +
			"</td>" +
			"<td class='response'>" +
				"<input type='text'>" +
			"</td>" +
		"</tr>"
	);
	row.find('div.button.remove').click(deleteRow);
	$('table.spam tbody').append(row);
	fixRows();
}

function deleteRow()
{
	var row = $(this).closest('tr');
	var label = row.find('td.re input').eq(0).val();
	if (!confirm("Remove rule " + label + "?"))
		return;
	row.remove();
	fixRows();
}

function fixRows()
{
	var alternate = false;
	$('table.spam tbody tr').each(function() {
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
	$('div.save.loading').show();
	$('button.save').hide();
	var data = getAsJSON();
	$.ajax({
		'type': 'POST',
		'url': "spam/submit",
		'data': "data=" + encodeURIComponent(data),
		'dataType': 'json',
		'async': true,
		'cache': false,
		'success': saveSuccess,
		'error': saveError
	});
}

function test()
{
	$('div.test.loading').show();
	$('button.test').hide();
	var data = getAsJSON();
	var message = $("#testtext").val();
	$.ajax({
		'type': 'POST',
		'url': "spam/test",
		'data': "data=" + encodeURIComponent(data) + "&message=" + encodeURIComponent(message),
		'dataType': 'json',
		'async': true,
		'cache': false,
		'success': testSuccess,
		'error': testError
	});
}

function getAsJSON()
{
	var data = [];
	$('table.spam tbody tr').each(function() {
		var row = $(this);
		data.push({
			're': row.find('td.re input').val(),
			'message': row.find('td.response input').val()
		});
	});
	return JSON.stringify(data);
}

function saveSuccess(data)
{
	$('div.save.loading').hide();
	$('button.save').show();
	if (saveFailure(data))
		return;
	alert("Saved");
}

function testSuccess(data)
{
	$('div.test.loading').hide();
	$('button.test').show();
	if (saveFailure(data))
		return;
	var resultsDiv = $("#spamresults").empty();
	var alternate = false;
	window.data = data;
	$(data.result).each(function(){
		if (!this.spam && $("#onlyspam").prop("checked"))
			return;
		var row = $("<div>");
		alternate = !alternate;
		row.addClass(alternate ? "odd" : "even");
		row.text(this.line);
		if (this.spam)
		{
			row.addClass("spam");
			row.attr("title", this.message);
		}
		resultsDiv.append(row);
	});
}

function saveFailure(data)
{
	$('input').removeClass("error");
	if (data.error)
	{
		var row = $('table.spam tr').eq(data.error.row + 1);
		var cell = row.find(data.error.col ? "td.response input" : "td.re input");
		cell.addClass("error");
		alert(data.error.msg);
		return true;
	}
	else
	{
		return false;
	}
}

function saveError()
{
	$('div.save.loading').hide();
	$('button.save').show();
	alert("Error saving spam rules");
}

function testError()
{
	$('div.test.loading').hide();
	$('button.test').show();
	alert("Error testing spam rules");
}
