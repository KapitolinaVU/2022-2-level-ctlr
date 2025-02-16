"""
Pipeline for CONLL-U formatting
"""
from pathlib import Path
from typing import List
import re

from pymystem3 import Mystem

from core_utils.article.article import SentenceProtocol, get_article_id_from_filepath, split_by_sentence
from core_utils.article.io import from_raw, to_cleaned, to_conllu
from core_utils.article.ud import OpencorporaTagProtocol, TagConverter
from core_utils.constants import ASSETS_PATH


# pylint: disable=too-few-public-methods


class InconsistentDatasetError(Exception):
    """
    IDs contain slips, number of meta and raw files is not equal, files are empty
    """


class EmptyDirectoryError(Exception):
    """
    directory is empty
    """


class CorpusManager:
    """
    Works with articles and stores them
    """

    def __init__(self, path_to_raw_txt_data: Path):
        """
        Initializes CorpusManager
        """
        self.path_to_raw_txt_data = path_to_raw_txt_data
        self._storage = {}
        self._validate_dataset()
        self._scan_dataset()

    def _validate_dataset(self) -> None:
        """
        Validates folder with assets
        """
        if not self.path_to_raw_txt_data.exists():
            raise FileNotFoundError

        if not self.path_to_raw_txt_data.is_dir():
            raise NotADirectoryError

        if not any(self.path_to_raw_txt_data.iterdir()):
            raise EmptyDirectoryError

        raw_files = [i for i in self.path_to_raw_txt_data.glob('*_raw.txt')]
        meta_files = [file for file in self.path_to_raw_txt_data.glob('*_meta.json')]

        if len(meta_files) != len(raw_files):
            raise InconsistentDatasetError

        for file in raw_files:
            if not file.stat().st_size:
                raise InconsistentDatasetError
        for file in meta_files:
            if not file.stat().st_size:
                raise InconsistentDatasetError

        list_of_raw_ids = [int(file.name[:file.name.index('_')]) for file in raw_files]
        list_of_meta_ids = [int(file.name[:file.name.index('_')]) for file in meta_files]

        if sorted(list_of_raw_ids) != list(range(1, len(list_of_raw_ids) + 1)):
            raise InconsistentDatasetError

        if sorted(list_of_meta_ids) != list(range(1, len(list_of_meta_ids) + 1)):
            raise InconsistentDatasetError

    def _scan_dataset(self) -> None:
        """
        Register each dataset entry
        """
        for file in self.path_to_raw_txt_data.glob("*_raw.txt"):
            article_id = get_article_id_from_filepath(file)
            self._storage[article_id] = from_raw(path=file)

    def get_articles(self) -> dict:
        """
        Returns storage params
        """
        return self._storage


class MorphologicalTokenDTO:
    """
    Stores morphological parameters for each token
    """

    def __init__(self, lemma: str = "", pos: str = "", tags: str = ""):
        """
        Initializes MorphologicalTokenDTO
        """
        self.lemma = lemma
        self.pos = pos
        self.tags = tags


class ConlluToken:
    """
    Representation of the CONLL-U Token
    """

    def __init__(self, text: str):
        """
        Initializes ConlluToken
        """
        self._text = text
        self._morphological_parameters = MorphologicalTokenDTO()
        self.position = 0

    def set_morphological_parameters(self, parameters: MorphologicalTokenDTO) -> None:
        """
        Stores the morphological parameters
        """
        self._morphological_parameters = parameters

    def get_morphological_parameters(self) -> MorphologicalTokenDTO:
        """
        Returns morphological parameters from ConlluToken
        """
        return self._morphological_parameters

    def get_conllu_text(self, include_morphological_tags: bool) -> str:
        """
        String representation of the token for conllu files
        """
        position = str(self.position)
        text = self._text
        lemma = self._morphological_parameters.lemma
        pos = self._morphological_parameters.pos
        xpos = '_'
        if include_morphological_tags and self._morphological_parameters.tags:
            feats = self._morphological_parameters.tags
        else:
            feats = '_'
        head = '0'
        deprel = 'root'
        deps = '_'
        misc = '_'
        return '\t'.join([position, text, lemma, pos, xpos, feats, head, deprel, deps, misc])

    def get_cleaned(self) -> str:
        """
        Returns lowercase original form of a token
        """
        cleaned = re.sub(r'[^\w\s]', '', self._text.lower())
        return cleaned


class ConlluSentence(SentenceProtocol):
    """
    Representation of a sentence in the CONLL-U format
    """

    def __init__(self, position: int, text: str, tokens: list[ConlluToken]):
        """
        Initializes ConlluSentence
        """
        self._position = position
        self._text = text
        self._tokens = tokens

    def _format_tokens(self, include_morphological_tags: bool) -> str:
        conllu_tokens = []
        for token in self._tokens:
            conllu_tokens.append(token.get_conllu_text(include_morphological_tags))
        return '\n'.join(conllu_tokens)

    def get_conllu_text(self, include_morphological_tags: bool) -> str:
        """
        Creates string representation of the sentence
        """
        return f"# sent_id = {self._position}\n# text = {self._text}\n" \
               f"{self._format_tokens(include_morphological_tags)}\n"

    def get_cleaned_sentence(self) -> str:
        """
        Returns the lowercase representation of the sentence
        """
        sentence = ''
        for token in self._tokens:
            cleaned_token = token.get_cleaned()
            if cleaned_token:
                sentence += cleaned_token + ' '
        sentence = sentence.strip()
        return sentence

    def get_tokens(self) -> list[ConlluToken]:
        """
        Returns sentences from ConlluSentence
        """
        return self._tokens


class MystemTagConverter(TagConverter):
    """
    Mystem Tag Converter
    """

    def convert_morphological_tags(self, tags: str) -> str:  # type: ignore
        """
        Converts the Mystem tags into the UD format
        """
        tag_list = re.findall(r'[а-я]+', tags)
        format_tags = {}

        for tag in tag_list:
            for category in (self.case, self.number, self.gender, self.animacy, self.tense):
                if tag in self._tag_mapping[category] and category not in format_tags:
                    format_tags[category] = self._tag_mapping[category][tag]
                    break

        feats = '|'.join(f'{cat}={val}' for cat, val in sorted(format_tags.items()))
        return feats

    def convert_pos(self, tags: str) -> str:  # type: ignore
        """
        Extracts and converts the POS from the Mystem tags into the UD format
        """
        pos = re.search(r'[A-Z]+', tags)[0]
        return self._tag_mapping[self.pos][pos]


class OpenCorporaTagConverter(TagConverter):
    """
    OpenCorpora Tag Converter
    """

    def convert_pos(self, tags: OpencorporaTagProtocol) -> str:  # type: ignore
        """
        Extracts and converts POS from the OpenCorpora tags into the UD format
        """

    def convert_morphological_tags(self, tags: OpencorporaTagProtocol) -> str:  # type: ignore
        """
        Converts the OpenCorpora tags into the UD format
        """


class MorphologicalAnalysisPipeline:
    """
    Preprocesses and morphologically annotates sentences into the CONLL-U format
    """

    def __init__(self, corpus_manager: CorpusManager):
        """
        Initializes MorphologicalAnalysisPipeline
        """
        self._corpus = corpus_manager
        self._mystem = Mystem()
        tag_mapping_path = Path(__file__).parent / 'data' / 'mystem_tags_mapping.json'
        self._tag_converter = MystemTagConverter(tag_mapping_path)

    def _process(self, text: str) -> List[ConlluSentence]:
        """
        Returns the text representation as the list of ConlluSentence
        """
        conllu_sentences = []
        result = (i for i in self._mystem.analyze(text))

        for idx_sent, sentence in enumerate(split_by_sentence(text)):
            conllu_tokens = []
            tokens = []

            for token in result:
                if token['text'] not in sentence:
                    continue
                sentence_subbed = re.sub(re.escape(token['text']), '', sentence, 1)
                if any(c.isalnum() for c in token['text']):
                    tokens.append(token)
                if not any(c.isalnum() for c in sentence_subbed):
                    break
            tokens.append({'text': '.'})

            for idx_token, token in enumerate(tokens, start=1):
                if 'analysis' in token and token['analysis']:
                    lex = token['analysis'][0]['lex']
                    pos = self._tag_converter.convert_pos(token['analysis'][0]['gr'])
                    tags = self._tag_converter.convert_morphological_tags(
                        token['analysis'][0]['gr'])
                else:
                    lex = token['text']
                    tags = ''
                    if token['text'].strip() == '.':
                        pos = 'PUNCT'
                    elif token['text'].isdigit():
                        pos = 'NUM'
                    else:
                        pos = 'X'

                conllu_token = ConlluToken(token['text'])
                morphology = MorphologicalTokenDTO(lex, pos, tags)
                conllu_token.position = idx_token
                conllu_token.set_morphological_parameters(morphology)
                conllu_tokens.append(conllu_token)

            conllu_sentence = ConlluSentence(idx_sent, sentence, conllu_tokens)
            conllu_sentences.append(conllu_sentence)

        return conllu_sentences

    def run(self) -> None:
        """
        Performs basic preprocessing and writes processed text to files
        """
        for article in self._corpus.get_articles().values():
            article.set_conllu_sentences(self._process(article.text))
            to_cleaned(article)
            to_conllu(article, include_morphological_tags=False)
            to_conllu(article, include_morphological_tags=True)


class AdvancedMorphologicalAnalysisPipeline(MorphologicalAnalysisPipeline):
    """
    Preprocesses and morphologically annotates sentences into the CONLL-U format
    """

    def __init__(self, corpus_manager: CorpusManager):
        """
        Initializes MorphologicalAnalysisPipeline
        """

    def _process(self, text: str) -> List[ConlluSentence]:
        """
        Returns the text representation as the list of ConlluSentence
        """

    def run(self) -> None:
        """
        Performs basic preprocessing and writes processed text to files
        """


def main() -> None:
    """
    Entrypoint for pipeline module
    """
    corpus_manager = CorpusManager(path_to_raw_txt_data=ASSETS_PATH)
    pipeline = MorphologicalAnalysisPipeline(corpus_manager)
    pipeline.run()


if __name__ == "__main__":
    main()
