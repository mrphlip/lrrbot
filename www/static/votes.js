function init()
{
	$('table.votes tr').each(function(){
		var row = $(this);
		row.data('currentvote', $.parseJSON(row.data('currentvote')));
		row.find('.vote.down').click(clickVote.bind(window, row, false));
		row.find('.vote.up').click(clickVote.bind(window, row, true));
	})
}
$(init);

function clickVote(row, vote)
{
	if (vote === row.data('currentvote'))
		return;
	row.find('div.votes').hide();
	row.find('div.loading').show();

	$.ajax({
		'type': 'POST',
		'url': "votes/submit",
		'data': "show=" + encodeURIComponent(row.data('show')) + "&id=" + encodeURIComponent(row.data('gameid')) + "&vote=" + (vote ? 1 : 0),
		'dataType': 'json',
		'async': true,
		'cache': false,
		'success': voteSuccess.bind(window, row, vote),
		'error': voteError.bind(window, row)
	})
}

function voteSuccess(row, vote)
{
	row.data('currentvote', vote);
	row.find('div.votes').show();
	row.find('div.loading').hide();
	row.find('div.vote.down').removeClass('inactive').removeClass('active').addClass(vote ? 'inactive' : 'active');
	row.find('div.vote.up').removeClass('inactive').removeClass('active').addClass(vote ? 'active' : 'inactive');
}

function voteError(row)
{
	row.find('div.votes').show();
	row.find('div.loading').hide();
}
