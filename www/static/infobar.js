$(function(){
	$(".infobar .showmore").click(function(){
		var $this = $(this);
		if ($this.hasClass("expand"))
		{
			$this.removeClass("expand").addClass("collapse");
			$this.parent().find(".rating").show();
			$this.parent().find(".stats").slideDown("fast");
		}
		else
		{
			$this.removeClass("collapse").addClass("expand");
			$this.parent().find(".rating").hide();
			$this.parent().find(".stats").slideUp("fast");
		}
	})
})
