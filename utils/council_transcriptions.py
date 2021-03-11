import glob
import os
import progressbar as pb
import re
import sys
import textract
from texts.models import Text, Language, TextType, Source


'''
[frl:       = Codeswitch naar Fries voor nederlandse spreker
[nl: = Codeswitch naar Nederlands vanuit het Fries
[frl-??:    = Niet specifiek herkend Fries dialect of Fries uitgesproken woord dat qua spelling of uitspraak niet als correct Fries wordt aangemerkt maar wel degelijk Fries klinkt. Altijd fonetisch genoteerd. 
[frl_??:    = zelfde als frl-?? (wordt in uiteindelijk dataset nog opgeschoond / genormaliseerd)
[frl-nl:    = Vernederlandst Fries woord
[nl-frl:    = Verfriest Nederlands woord
[frl-sw:    = Herkend als Zuid-west Fries dialect
[nl-overlap: = Betekenis nu niet bekend, ingevoerd door taalspecialist. Betekenis wordt nagevraagd.
'''

output_dir = '/vol/tensusers/mbentum/FRISIAN_ASR/'

def get_all_transcriptions_with_tags(error = False,save = False, with_original=False):
	tt = Text.objects.filter(source__name = 'frisian council transcripts').filter(error = error)
	o = []
	for t in tt:
		o.append(t.transcription.line_with_tags)
		if with_original:
			o.append(t.transcription.line)
			o.append('-'*9)
	if save: 
		filename = output_dir + 'labels_with_tags'
		if error: filename += '_error'
		if with_original:filename += '_with_original'
		filename += '.txt'
		with open(filename,'w') as fout:
			fout.write('\n'.join(o))
	return o


nsn = 'geluid,oversturing,ruis,klok,hamer,foto,applaus,microfoon,klop'
nsn += ',tafel,koffie,stoel,water,typen,pen,papier,geklap,telefoon'
nsn = nsn.split(',')
spn = 'spraak,kuch,lach,zucht,za,slikken,geroezemoes,ademhaling'
spn = ',lipsmack,he,hè,eh,nies,hoest'
spn = spn.split(',')


filename_labels = '/vol/tensusers3/Frisiansubtitling/Downloads-Humainr/First_Batch_20210218/Transcriptions/labels.txt'
filename_protocol= '/vol/tensusers3/Frisiansubtitling/Downloads-Humainr/First_Batch_20210218/Transcriptions/protocol_en_tags.txt'

dutch = Language.objects.get(name='Dutch')
frisian = Language.objects.get(name='Frisian')
dutch_frisianized = Language.objects.get(name='Dutch_frisianized')
frisian_dutchized = Language.objects.get(name='Frisian_dutchized')
english = Language.objects.get(name='English')
ld = {'FRL':frisian,'NL':dutch,'frl':frisian,'nl':dutch,'frl-nl':frisian_dutchized}
ld.update({'nl-frl':dutch_frisianized, 'frl-sw':frisian,'en':english,'frl_??':'frl-??'})
ld.update({'frl-??':'frl-??'})

cs = 'frl,nl,frl-??,frl_??,frl-nl,nl-frl,frl-sw,nl-overlap,overlap-nl,en'.split(',')
tags = dict([[x,'code_switch'] for x in cs])
tags.update({'++':'enrich','--':'cleaning','eh':'eh','he':'eh','hè':'eh'})

source = Source.objects.get(name= 'frisian council transcripts')
text_type = TextType.objects.get(name = 'manual transcription')

def get_transcriptions_text():
	return open(filename_labels).read().split('\n')

def make_transcriptions():
	transcription = get_transcriptions_text()
	output = []
	for line in transcription:
		output.append( Transcription(line) )
	return output

def load_transcriptions_in_database(transcriptions=None, save = False):
	if not transcriptions: transcriptions = make_transcriptions()
	o = []
	for t in transcriptions:
		o.append(add_transcription(t,save))
	return o

def add_transcription(t, save = False):
		error = t.get_bracket_error or t.bracket_error or t.tag_error
		multiple_languages = True if len(t.languages) > 1 else False
		o =Text(filetype = 'txt',raw_text = t.text, transcription_meta = t.line, 
			main_language = t.language, source = source, text_type= text_type,
			start_time = t.start, end_time = t.end, wav_filename = t.wav,
			multiple_languages = multiple_languages, error = error)
		if not save: return o
		try: o.save()
		except:
			print('could not save:',t)
			print(sys.exc_info())
		else:
			for language in t.languages:
				o.all_languages.add(language)
		return o
		

class Transcription:
	def __init__(self,line):
		self.line = line
		self.wav, self.l, self.start, self.end, self.text= line.split('\t')
		self.start = float(self.start)
		self.end = float(self.end)
		self.duration = self.end - self.start
		self.language = ld[self.l]
		self.extract_brackets_and_words()

	def __repr__(self):
		t = self.text if len(self.text) < 75 else self.text[:75] + '... '
		m = t.ljust(80) + ' | ' + self.language.name.ljust(8) 
		m += ' | ' + str(round(self.duration))
		return m

	def extract_brackets_and_words(self):
		self.brackets = []
		brackets, self.line_without_brackets,word_chunks,error = get_brackets(self.text)
		self.get_bracket_error = error
		for b in brackets:
			self.brackets.append(Bracket(b))
		self.words = []
		i = 0
		for chunk in word_chunks:
			for w in chunk:
				self.words.append(Word(w,self.language,False))
			if i < len(self.brackets):
				b = self.brackets[i]
				if b.error:continue
				self.words.extend(b.words)
				i +=1

	@property
	def bracket_error(self):
		e1 = sum([b.error for b in self.brackets]) > 0
		return e1 or self. get_bracket_error
		
	@property
	def tag_error(self):
		return sum([b.tag_error for b in self.brackets]) > 0

	@property
	def languages(self):
		return list(set([w.language for w in self.words if w.language]))

	@property
	def text_with_tags(self):
		d = {dutch:'-nl',frisian:'-fr',dutch_frisianized:'-nl',frisian_dutchized:'-fr',english:'-eng'}
		output = []
		for word in self.words:
			if word.word == '$$': continue
			if word.is_word and word.language: 
				if word.language == 'frl-??': output.append('<spn>')
				else: output.append(word.word + d[word.language])
			else:output.append(word.word)
		return ' '.join(output).lower()
		
	@property
	def line_with_tags(self):
		return '\t'.join([self.wav,str(self.start),str(self.end),self.text_with_tags])
			


class Word:
	def __init__(self,word,language, code_switched,tag = '',is_word = True):
		if word == '<eh>':
			if tag == '': tag = 'eh' 
			language = ''
			code_switched = False
			word = '<spn>'
		self.word = word
		self.original_word = word
		self.language = language
		self.code_switched = code_switched
		self.tag = tag
		self.is_word = is_word
		self.check()

	def __repr__(self):
		cs = ' | code_switched' if self.code_switched else ''
		l = self.language.name if self.language else 'Unk'
		return self.word.ljust(20) + ' | ' + l.ljust(8) + cs
	
	def check(self):
		for char in list('[]{}:'):
			if char in self.word:
				self.is_word = False
				self.word = '<nsn>'

class Bracket:
	def __init__(self,bracket):
		self.bracket = bracket
		self.text = re.sub(':+',':',bracket[1:-1])
		self.error = False
		self.tag_error = False
		self.t, self.tag_text = self.text, self.text
		if ':' in self.text:
			if self.text.count(':') == 1: self.t,self.tag_text = self.text.split(':') 
			elif self.text.count(':') == 2: 
				self.t,temp,self.tag_text = self.text.split(':') 
				self.tag_text = temp + ':' +self.tag_text
			else: self.error = True
		if not self.error:
			try:self.tag = tags[self.t]
			except: 
				self.tag = self.t
				self.tag_error = True
			self.code_switch = self.t in cs
			self.language = None
			self.words = []
			if self.code_switch: 
				try: self.language = ld[self.t]
				except: pass 
				self.make_words()
			else: 
				label = ''
				for item in nsn:
					if item in self.tag_text: label = '<nsn>'
				if not label:
					for item in spn:
						if item in self.tag_text: label = '<spn>'
				if not label: 
					print('could not categorize tag text:',self.tag_text,'setting word to nsn')
					label = '<nsn>'
				self.words.append(Word(label,'',False,False))


	def __repr__(self):
		return self.text + ' | ' + self.tag + ' | '  + str(self.error) + ' | ' + str(self.tag_error)

		
	def make_words(self):
		for w in self.tag_text.split(' '):
			self.words.append(Word(w,self.language,True,self.tag))
	



	
	
def get_brackets(line):
	line = line.replace('[eh]','<eh>')
	line = re.sub('[^ ]<eh>',' <eh>',line)
	line = re.sub('<eh>[^ ]','<eh> ',line)
	line_without = []
	brackets = []
	st, et,old_et = -1,-1,0
	error =False 
	while True:
		st_check = line.find('[',st+1)
		if 0 < st_check < et: 
			error = True
		st = line.find('[',et+1)
		et = line.find(']',et+1)
		if 0 <= st < et:
			line_without.append( line[old_et:st] )
			brackets.append(line[st:et+1])
			old_et = et+1
		elif st > et: 
			st = et+1
			error = True
		else:
			line_without.append( line[old_et:] )
			break
		if error:
			break
	words = []
	for chunk in line_without:
		words.append([w for w in chunk.split(' ') if w])
	return brackets,line_without,words,error
