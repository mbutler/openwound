#!/usr/bin/perl
use strict;
use warnings;
no warnings 'uninitialized';

use CGI::Carp 'fatalsToBrowser';
use CGI qw/:standard *table/;
use Lingua::EN::Tagger;

my $app_title = 'Open Wound 1.0';

# Possible Lingua::EN::Tagger tags.
my @tags = qw/cc cd det ex fw in jj jjr jjs ls md nn nnp nnps nns pdt pos prp
              prps rb rbr rbs rp sym to uh vb vbd vbg vbn vbp vbz wdt wp wps
              wrb pp ppc ppd ppl ppr pps lrb rrb/;

# 977 most common English words to skip.
my @common_words = qw/the of and to a in that is was he for it with as his on be at by i this had not are but from or have an they which one were you all her she there would their we him been has when who will no more if out its so up said what about than into them can only other time new some could these two may first then do any like my now over such our man me even most made after also well did many before must years back through much where your way down should because long each just state people those too how mr little good world make very year still see own work men day get here old between both life being under three never know same last another while us off might great states go come since against right came take used himself few house american use place during high without again home around small however found mrs part school thought went say general once upon every left war dont does got united number hand course water until always away public something fact less through far put head think called set almost enough end took government night yet system better four nothing told eyes city going president why days present point didnt look find asked second group later next room social business knew program give half side face toward white five let young form given per order large several national important possible rather big among case often early john things looked ever become best need within felt along children saw church light power least family development interest others open thing seemed want area god members mind help country service turned door done law although whole line problem sense certain different kind began thus means matter perhaps name times york itself action human above week company free example hands local show history whether act either gave death feet today across body past quite taken anything field having seen word car experience im money really class words already college information tell making sure themselves together full air shall held known period keep political real miss probably century question seems behind cannot major office brought special whose boy cost federal economic self south problems heard six study ago became moment run available job street result short west age change position board individual reason turn close areas am love society level court control true community force ill type front wife center future hard policy seem clear town voice wanted woman common department girl black party land necessary surface top following rate sometimes tax mother music students low military child further third red university able education feel provide effect morning nations total near road stood art figure outside north million washington leave value cut usually fire plan play sound therefore english evidence table book strong range believe living peace various mean modern says soon lines looking schools single alone longer minutes personal process secretary gone idea months situation women increase nor section america pressure private started dark ground dr east nature stage finally kept call father needed values greater expected view thats everything space ten union basis spirit brown required taking complete conditions except hundred late moved ones wrote hours return support attention hour live particular recent data hope person beyond coming dead middle cold costs else forces heart material couldnt developed feeling fine story inside lost read report research twenty industry instead miles son wall added amount followed makes move pay basic cant including building defense hold reached simply tried central wide committee equipment picture island simple actually care religious shown friends river beginning getting higher medical received rest sort boys doing floor foreign terms trying indeed administration cent difficult subject especially meeting earth market paper passed walked blue bring county labor hall natural police similar training england final growth international property talk working written congress food girls start wasnt answer hear issue purpose suddenly weeks western needs stand youre considered countries fall hair likely nation lay sat cases color entire french happened paid production ready results square difference earlier involved meet step stock thinking william christian club letter aid increased lot month particularly whom below effort knowledge lower points sent trade using industrial size yes bad bill certainly eye ideas temperature addition deal due method methods moral reading decided directly nearly neither questions record showed statements throughout anyone programs try according member physical science services southern hot remember soviet strength comes normal trouble understand volume population summer trial appeared bed concerned district led merely sales student direction friend maybe piece ran army blood continued degree direct evening game green husband list literature plane association average cause generally george influence met provided seven systems chance changes easy former freedom hell meaning opened shot spring ways works wrong fear organization planning series term theory ask effective lead myself respect stopped wouldnt clearly efforts forms groups movement plant truth worked based beautiful consider farm horse hotel mans note press somewhat treatment arms charge placed apparently carried feed herself hes hit ive length numbers operation persons radio reaction born manner oh recently running approach chief deep eight immediately larger performance price sun couple daily gun lived main stop straight heavy image march opportunity technical test understanding writing additional british decision described determined europe fiscal negro progress served window cars character quality religion reported responsibility steps appear serious account ball communist corner design learned moving post activity forward pattern pool poor slowly specific staff types activities audience choice filled growing justice latter letters nuclear obtained returned democratic doubt obviously parts plans thirty established figures foot function include leaders mass saying standard stay attack closed drive gives speak waiting whatever completely covered faith hospital language race season wish built designed distance effects extent glass income lack products ahead analysis corps elements existence expect firm married principle theres/;

my %tag_input; # Values for filling in the tag fields.

if (param('action') =~ /^\s*tag\s*$/i) {

   $app_title .= ' | [output]';

   # Remove possible leftovers from previous generation cycle.
   Delete(qw/substitution recombined/);

   my $tagger = new Lingua::EN::Tagger;
   my $tagged_xml = $tagger->add_tags(param('source'));

   my %noun_phrases = $tagger->get_noun_phrases($tagged_xml);
   param(noun_phrases => join ', ', keys %noun_phrases);

   # Extract and store occurences for each tag.
   while ($tagged_xml =~ m!<([^>]+)>([^<]+)</\1>!g) {
      $tag_input{$1}{lc $2}++;
   }

   # Convert XML-type output to word/TAG format.
   $tagged_xml =~ s!<([^>]+)>([^<]+)</\1>!$2/\U$1!g;
   param(tagged_text => $tagged_xml);
}
elsif (param('action') =~ /^\s*generate\s*$/i) {

   $app_title .= ' | [generated]';

   # Prepare a hash of tag occurences for convenient randomization.
   my %variants;
   foreach (@tags) {
      $variants{$_} = [ split /\s+/, param($_) ] if param($_);
   }

   # Get a list of common words to skip.
   my $common_words_limit = param('common_limit') || @common_words;
   my %common_words_checker;
   @common_words_checker{@common_words[0 .. ($common_words_limit - 1)]} = ();

   # Subroutine performing random substitusion. Called from the regex below.
   my $substitute_match = sub {
      my ($part, $tag) = @_;

      return $part if exists $common_words_checker{lc $part};
      my $part_variants = $variants{lc $tag}
         or return $part;

      my $rand_part = $part_variants->[rand(@$part_variants)];
      return $rand_part;
   };


   # Generate "substitution" and "recombined" fields.

   my $text = param('tagged_text');

   $text =~ s!(\S+)/([A-Z]+)!$substitute_match->($1,$2) . "/$2"!ge;
   param(substitution => $text);

   $text =~ s!\s+(?=\S+/(PP[CDLRS]?|RRB))!!g; # remove junk space.
   $text =~ s!(^\s*|/PP\s+)(\S+)!$1\u$2!g; # capitalize beginnings of sentences.
   $text =~ s!/LRB\s+!!g; # and more junk space and some tags.
   $text =~ s!/[A-Z]+!!g; # remove all tags.
   param(recombined => $text);
}
else {
   # Initial phase. Perform nothing, just display form.
   $app_title .= ' | [input]';
}

# Output the form. Field value substitution is done by CGI.pm from param() values
# possibly set in the above code.

print header,
      start_html(-title => $app_title),
      h1($app_title),
      start_form,
      p(strong('Input text:'), br,
        textarea(-name => 'source', -rows => 10, -columns => 100)),
      p(submit(-name => 'action', -value => '   Tag   ')),
      p(strong('Tagged text:'), br,
        textarea(-name => 'tagged_text', -rows => 10, -columns => 100)),
      p(strong('Common:'), textfield(-name => 'common_limit', size => 3)),
      p(strong('Noun phrases:'), br, textarea(-name => 'noun_phrases',
                                              -rows => 4, -columns => 100)),
      start_table();

# Generate tag fields.

my $i;
foreach (@tags) {
   param($_ => join(' ', sort keys %{ $tag_input{$_} })) if %tag_input;
   print '<tr>' if $i++ % 3 == 0;
   print td(strong("\U$_:")),
         td(textfield(-name => $_, -size => 30));
}

print end_table(),
      p(submit(-name => 'action', -value => 'Generate')),
      p(strong('substitution:'), br,
        textarea(-rows => 10, -name => 'substitution', -columns => 100)),
      p(strong('recombined:'), br,
        textarea(-rows => 10, -name => 'recombined', -columns => 100)),
      end_form;





























