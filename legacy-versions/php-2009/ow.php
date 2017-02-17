<?php 

include('PosTagger.php');

function printTag($tags) {
        foreach($tags as $t) {
                echo $t['token'] . "/" . $t['tag'] .  " ";
        }
        echo "\n";
}

$tagger = new PosTagger('lexicon.txt');
$tags = $tagger->tag($_POST['input']);
printTag($tags); 

?>