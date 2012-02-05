<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<title>Open Wound 2</title>
<style>
.textarea
{
	border-style:none;
	width:640px;
	height:100px;
	background-color:#EBEBEB;
	display:block;
	overflow-y: auto;
}
</style>
</head>

<body>

<?php 
// Possible POS tags
$taglist = "CC CD DET EX FW IN JJ JJR JJS LS MD NN NNP NNPS NNS PDT POS PRP PRPS RB RBR RBS RP SYM TO UH VB VBD VBG VBN VBP VBZ WDT WP WPS WRB PP PPC PPD PPL PPR PPS LRB RRB";
$tagarray = explode(' ', $taglist);

$input = $_POST['input'];

include('PosTagger.php');

function printTag($tags) 
{
        foreach($tags as $t) 
		{
         	echo $t['token'] . "/" . $t['tag'] .  " ";
        }
		
        echo "\n";
}

$tagger = new PosTagger('lexicon.txt');
$tags = $tagger->tag($input);

echo '<form name = "tag-form" method = "POST" action = "tag.php" >';
echo '<textarea id = "input" name = "input" class = "textarea">';
echo $input;
echo '</textarea>';
echo '<input type="submit" value="Tag" />';


echo '<form name = "generate-form" method = "POST" action = "index.php" >';
echo '<textarea id = "output" name = "output" class ="textarea">';
printTag($tags);
echo '</textarea>';
echo '<input type="submit" value="Generate" />';
echo '</form>';


 

?>




</body>
</html>
