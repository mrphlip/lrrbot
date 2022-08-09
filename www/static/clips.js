function init()
{
	$('table.clips tr').each(function(){
		var row = $(this);
		row.data('currentrating', $.parseJSON(row.data('currentrating')));
		row.find('.thumbnail, .main').css('cursor', 'pointer').click(showPreview.bind(window, row));
		row.find('.vote.down').click(clickVote.bind(window, row, false));
		row.find('.vote.up').click(clickVote.bind(window, row, true));
	});
	window.currentPreview = null;
}
$(init);

function showPreview(row)
{
	if (row.data('slug') == window.currentPreview) {
		$("#preview").hide();
		$("#preview td").empty();
		window.currentPreview = null;
	} else {
		$("#preview").insertAfter(row).show();
		$("#preview td").html(row.data('embed'));
		window.currentPreview = row.data('slug');
	}
}

function clickVote(row, vote)
{
	if (vote === row.data('currentvote'))
		return;
	row.find('div.votes').hide();
	row.find('div.loading').show();

	$.ajax({
		'type': 'POST',
		'url': "submit",
		'data': "slug=" + encodeURIComponent(row.data('slug')) + "&vote=" + (vote ? 1 : 0) + "&_csrf_token=" + encodeURIComponent(window.csrf_token),
		'dataType': 'json',
		'async': true,
		'cache': false,
		'success': voteSuccess.bind(window, row, vote),
		'error': voteError.bind(window, row)
	})
}

function voteSuccess(row, vote, data)
{
	row.data('currentvote', vote);
	row.find('div.votes').show();
	row.find('div.loading').hide();
	row.find('div.vote.down').removeClass('inactive').removeClass('active').addClass(vote ? 'inactive' : 'active');
	row.find('div.vote.up').removeClass('inactive').removeClass('active').addClass(vote ? 'active' : 'inactive');
	row.removeClass('incomplete').addClass('complete');
}

function voteError(row)
{
	row.find('div.votes').show();
	row.find('div.loading').hide();
}
