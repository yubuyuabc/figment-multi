'''
Created on Oct 27, 2015

@author: yadollah
'''
import sys, os, string
import theano,numpy, codecs, h5py, yaml, logging
from src.common.myutils import convertTargetsToBinVec, yyreadwordvectors, get_ngram_seq, \
    read_embeddings_vocab, buildtypevecmatrix, buildcosinematrix,\
    read_embeddings, get_ent_names
from _collections import defaultdict
from collections import namedtuple
logging.basicConfig(format='%(asctime)s : %(levelname)s : %(message)s', level=logging.INFO)
logger = logging.getLogger('makefueldataset')
import src.common.myutils as cmn
from fuel.datasets import H5PYDataset
from unidecode import unidecode
import numpy as np
padTag = '<PAD>'
unkTag = '<UNK>'
startTag = '<S>'
endTag = '</S>'

def gen_new_ds(e2names, e2types, max_name=1, outfile='train.txt'):
    f = open(outfile, 'w')
    for mye in e2names:
        names = get_ent_names(e2names[mye], max_name)
        targets = e2types[mye]
        for nm in names:
            line = '\t'.join([mye, nm.strip(), targets[0]])
            line += '\t' + ' '.join(targets[1:])
            f.write(line + '\n')
    f.close()

def generate_name_dataset(config):
    trainfile = config['Etrain']
    devfile = config['Edev']
    testfile = config['Etest']
    targetTypesFile=config['typefile']
    max_names = [int(n) for n in config['name_num'].split()]
    dsdir = config['dsdir']
    (t2idx, _) = cmn.loadtypes(targetTypesFile)
    _ = len(t2idx)
    (etrain2types, etrain2names, _) = cmn.load_entname_ds(trainfile, t2idx)
    logger.info("number of train examples: %d",len(etrain2names))
    (etest2types, etest2names, _) = cmn.load_entname_ds(testfile, t2idx)
    logger.info("number of test examples: %d",len(etest2names))
    (edev2types, edev2names, _) = cmn.load_entname_ds(devfile, t2idx)
    logger.info("number of dev examples: %d", len(edev2names))

    logger.info('number of names for each entity in trn,dev,test: %s', max_names)
    logger.info('generating new datasets based on entity names')
#     dsdir = dsdir + 'maxname'  + ','.join([str(n) for n in max_names])
#     if not os.path.exists(dsdir): os.makedirs(dsdir)
    gen_new_ds(etrain2names, etrain2types, max_names[0], outfile = dsdir + '/train.txt')
    gen_new_ds(edev2names, edev2types, max_names[1], outfile = dsdir + '/dev.txt')
    gen_new_ds(etest2names, etest2types, max_names[2], outfile = dsdir + '/test.txt')

def load_ent_ds(dsfile):
    logger.info('loading dataset %s', dsfile)
    MentionType = namedtuple(
    "MentionType", ["entityId",          # 
                   "name",         # Name of the entity type
                   "notableType",  # How many entities have this type?
                   "alltypes",    # How often does this type appear
                   ])
    f = open(dsfile)
    f = codecs.open(dsfile, encoding='utf-8')

    instances = []
    for line in f:
        parts = line.strip().split('\t')
        entid = parts[0]
        name = parts[1]
        name = unidecode(name)
        types = [parts[2].strip()]
        if len(parts) >= 4:
            for t in parts[3].split():
                if t not in types:
                    types.append(t)
        instances.append(MentionType(entid, name, parts[2], types))
    return instances

def build_char_vocab(mentions):
    MIN_FREQ = 70#len(mentions) / 3000
    char2freq = defaultdict(lambda: 0)
    for mn in mentions:
        onename = mn.name
        for c in onename:
            char2freq[c] += 1
    char_vocab = []
    for c in char2freq:
        if char2freq[c] < MIN_FREQ:
            continue
        char_vocab.append(c)
    char_vocab.extend([padTag, unkTag, startTag, endTag])
    logger.info('distinct char_vocab %s and #=%d', char_vocab, len(char_vocab))
    char_to_ix = {ch: i for i, ch in enumerate(char_vocab)}
    ix_to_char = {i: ch for i, ch in enumerate(char_vocab)}
    return char_to_ix, ix_to_char

def build_word_vocab(mentions):
    MIN_FREQ = 1#len(mentions) / 1000
    word2freq = defaultdict(lambda: 0)
    for mn in mentions:
        words = mn.name.split(' ')
        for w in words:
            word2freq[w] += 1
    vocab = []
    for w in word2freq:
        if word2freq[w] < MIN_FREQ:
            continue
        vocab.append(w)
    vocab.extend([padTag, unkTag, startTag, endTag])
    logger.info('distinct word vocab number = %d', len(vocab))
    word_to_ix = {w: i for i, w in enumerate(vocab)}
    ix_to_word = {i: w for i, w in enumerate(vocab)}
    return word_to_ix, ix_to_word


def get_ngrams(name, ngram):
    ngrams = []
    for i in range(len(name) - ngram + 1):
        ng = name[i:i + ngram].replace(' ', '_') #bcaz for word2vec training we replaced space with _
        ngrams.append(ng)
    return ngrams

def build_ngram_vocab(mentions, ngram=4, MIN_FREQ = 5):
    #len(mentions) / 1000
    ngram2freq = defaultdict(lambda: 0)
    name2ngrams = {}
    for mn in mentions:
        ngrams = get_ngrams(mn.name, ngram)
        name2ngrams[mn.name] = ngrams
        for ng in ngrams:
            ngram2freq[ng] += 1   
    vocab = []
    for ng in ngram2freq:
        if ngram2freq[ng] < MIN_FREQ:
            continue
        vocab.append(ng)
    vocab.extend([padTag, unkTag, startTag, endTag])
    #logger.info('distinct word vocab number = %d', len(vocab))
    ngram_to_ix = {ng: i for i, ng in enumerate(vocab)}
    ix_to_ngram = {i: ng for i, ng in enumerate(vocab)}
    return ngram_to_ix, ix_to_ngram, name2ngrams

def build_letters_ds(trnMentions, devMentions, tstMentions, t2idx, dsdir, vectorfile=None, max_len_name=30):
    char_to_idx, idx_to_char = build_char_vocab(trnMentions) #train for characters because we only use entities names for characters
    totals = len(trnMentions) + len(devMentions) + len(tstMentions) 
    input_letters = numpy.zeros(shape=(totals, max_len_name), dtype='int32')
    for i, men in enumerate(trnMentions + devMentions + tstMentions):
        name = men.name
        input_letters[i] = get_ngram_seq(char_to_idx, name, max_len_name)
    print input_letters.shape
    fuelfile = dsdir +'_letters.h5py'
    f = h5py.File(fuelfile, mode='w')
    features = f.create_dataset('letters', input_letters.shape, dtype='int32')  # @UndefinedVariable
    features.attrs['voc2idx'] = yaml.dump(char_to_idx, default_flow_style=False)
    features.attrs['idx2voc'] = yaml.dump(idx_to_char, default_flow_style=False)
    features.attrs['vocabsize'] = len(char_to_idx)
    features[...] = input_letters
    features.dims[0].label = 'letters'
    nsamples_train = len(trnMentions); nsamples_dev = len(devMentions);
    split_dict = {
        'train': {'letters': (0, nsamples_train)},
        'dev': {'letters': (nsamples_train, nsamples_train + nsamples_dev)}, 
        'test': {'letters': (nsamples_train + nsamples_dev, totals)}}
    f.attrs['split'] = H5PYDataset.create_split_array(split_dict)
    f.flush()
    f.close()
    logger.info('building letters dataset finished. It saved in: %s', fuelfile)
    if vectorfile is None: 
        return
    embeddings, vectorsize = read_embeddings_vocab(vectorfile, vocab=char_to_idx, num=-1)
    logger.info('size of embedding matrix to save is: (%d, %d)', embeddings.shape[0], embeddings.shape[1])
    with h5py.File(dsdir + "_letters_embeddings.h5py", mode='w') as fp:
        vectors = fp.create_dataset('vectors', compression='gzip',
                                    data=embeddings)
        vectors.attrs['vectorsize'] = vectorsize

def build_words_ds(trnMentions, devMentions, tstMentions, t2idx, dsdir, vectorfile, max_num_words=10, upto=None):
    word_to_idx, idx_to_word = build_word_vocab(trnMentions+devMentions+tstMentions) #train for characters because we only use entities names for characters
    logger.info('word vocab size: %d', len(word_to_idx))
    totals = len(trnMentions) + len(devMentions) + len(tstMentions) 
    input_words = numpy.zeros(shape=(totals, max_num_words), dtype='int32')
    for i, men in enumerate(trnMentions + devMentions + tstMentions):
        name = men.name
        words = name.split()
        input_words[i] = get_ngram_seq(word_to_idx, words, max_len=max_num_words)
    logger.info('shape of words dataset: %s', input_words.shape)
    hdf5_file = dsdir + '_words.h5py'
    f = h5py.File(hdf5_file, mode='w')
    features = f.create_dataset('words', input_words.shape, dtype='int32')  # @UndefinedVariable
    
    features.attrs['voc2idx'] = yaml.dump(word_to_idx, default_flow_style=False)
    features.attrs['idx2voc'] = yaml.dump(idx_to_word, default_flow_style=False)
    features.attrs['vocabsize'] = len(word_to_idx)
    features[...] = input_words
    features.dims[0].label = 'words'
    nsamples_train = len(trnMentions); nsamples_dev = len(devMentions);
    split_dict = {
        'train': {'words': (0, nsamples_train)},
        'dev': {'words': (nsamples_train, nsamples_train + nsamples_dev)}, 
        'test': {'words': (nsamples_train + nsamples_dev, totals)}}
    f.attrs['split'] = H5PYDataset.create_split_array(split_dict)
    f.flush();f.close()
    logger.info('Building words dataset finished. It saved in: %s', hdf5_file)
    logger.info('writing word embeddings')
    idx2embeddings, vectorsize = read_embeddings_vocab(vectorfile, vocab=word_to_idx, num=upto)
    with h5py.File(dsdir + "_words_embeddings.h5py", mode='w') as fp:
        vectors = fp.create_dataset('vectors', compression='gzip',
                                    data=idx2embeddings)
        vectors.attrs['vectorsize'] = vectorsize
        
def build_ngram_ds(trnMentions, devMentions, tstMentions, t2idx, dsdir, vectorfile, ngram, max_num_ngrams=98, upto=-1):
    ngram_to_idx, idx_to_word, name2ngrams = build_ngram_vocab(trnMentions+devMentions+tstMentions,ngram=ngram, MIN_FREQ=5) #train for characters because we only use entities names for characters
    logger.info('ngram%d vocab size: %d', ngram, len(ngram_to_idx))
    totals = len(trnMentions) + len(devMentions) + len(tstMentions) 
    input_words = numpy.zeros(shape=(totals, max_num_ngrams), dtype='int32')
    for i, men in enumerate(trnMentions + devMentions + tstMentions):
        name = men.name
        ngrams = name2ngrams[name]
        input_words[i] = get_ngram_seq(ngram_to_idx, ngrams, max_len=max_num_ngrams)
    print input_words.shape
    ngram_label = 'ngrams' + str(ngram)
    hdf5_file = dsdir + '_ngrams'+str(ngram)+'.h5py'
    f = h5py.File(hdf5_file, mode='w')
    features = f.create_dataset(ngram_label, input_words.shape, dtype='int32')  # @UndefinedVariable
    
    features.attrs['voc2idx'] = yaml.dump(ngram_to_idx, default_flow_style=False)
    features.attrs['idx2voc'] = yaml.dump(idx_to_word, default_flow_style=False)
    features.attrs['vocabsize'] = len(ngram_to_idx)
    features[...] = input_words
    features.dims[0].label = ngram_label
    nsamples_train = len(trnMentions); nsamples_dev = len(devMentions);
    split_dict = {
        'train': {ngram_label: (0, nsamples_train)},
        'dev': {ngram_label: (nsamples_train, nsamples_train + nsamples_dev)}, 
        'test': {ngram_label: (nsamples_train + nsamples_dev, totals)}}
    f.attrs['split'] = H5PYDataset.create_split_array(split_dict)
    f.flush();f.close()
    logger.info('Building ngram%d dataset finished. It saved in: %s', ngram, hdf5_file)
    if vectorfile is None or vectorfile == '': 
        return
    logger.info('Now, writing ngram embeddings')
    embeddings, vectorsize = read_embeddings_vocab(vectorfile, vocab=ngram_to_idx, num=upto)
    logger.info('size of embedding matrix to save is: (%d, %d)', embeddings.shape[0], embeddings.shape[1])
    with h5py.File(dsdir + "_" + ngram_label + "_embeddings.h5py", mode='w') as fp:
        vectors = fp.create_dataset('vectors', compression='gzip',
                                    data=embeddings)
        vectors.attrs['vectorsize'] = vectorsize        


def load_embmatirx(dsembpath, num_examples, vecsize=200, upto=None):
    logger.info('loading mention embeddings from :%s', dsembpath)
    mymatrix = numpy.zeros(shape=(num_examples, vecsize), dtype='float32')
    with open(dsembpath) as fp:
        for i, myline in enumerate(fp):
            vec = myline.split('\t')[4]
            vv = vec.split()
            if len(vv) != vecsize:
                print i, myline.split('\t')[1:3]
                continue
            mymatrix[i] = [float(v) for v in vv]
    return mymatrix



def build_entvec_ds(trnMentions, devMentions, tstMentions, t2idx, hdf5_file, vectorfile, upto=-1):
    (embeddings, word2idx, vectorsize) = read_embeddings(vectorfile, upto)
    totals = len(trnMentions) + len(devMentions) + len(tstMentions) 
    input_entvec = numpy.zeros(shape=(totals, vectorsize), dtype='float32')
    for i, men in enumerate(trnMentions + devMentions + tstMentions):
        mye = men.entityId
        entvec = numpy.zeros(vectorsize)
        if mye in word2idx:
            entvec = embeddings[word2idx[mye]]
        input_entvec[i] = entvec
    print input_entvec.shape
    hdf5_file += '_entvec.h5py'
    f = h5py.File(hdf5_file, mode='w')
    features = f.create_dataset('entvec', input_entvec.shape, dtype='float32')  # @UndefinedVariable
    features.attrs['vectorsize'] = vectorsize
    features[...] = input_entvec
    features.dims[0].label = 'entity_vector'
    nsamples_train = len(trnMentions); nsamples_dev = len(devMentions);
    split_dict = {
        'train': {'entvec': (0, nsamples_train)},
        'dev': {'entvec': (nsamples_train, nsamples_train + nsamples_dev)}, 
        'test': {'entvec': (nsamples_train + nsamples_dev, totals)}}    
    f.attrs['split'] = H5PYDataset.create_split_array(split_dict)
    f.flush()
    f.close()
    logger.info('Building entityVec dataset finished. It saved in: %s', hdf5_file)

def build_hsNgram_ds(config, trnMentions, devMentions, tstMentions, t2idx, hdf5_file, embpath, vectorsize=200, upto=-1):
    emb_version = os.path.basename(embpath)
    nsamples_train = len(trnMentions); nsamples_dev = len(devMentions);
    totals = nsamples_train + nsamples_dev + len(tstMentions) 
    input_hsngram_matrix = numpy.zeros(shape=(totals, vectorsize), dtype='float32')
    input_hsngram_matrix[0:nsamples_train] = load_embmatirx(embpath+'/train.txt', len(trnMentions), vectorsize, upto)
    input_hsngram_matrix[nsamples_train:nsamples_train+nsamples_dev] = load_embmatirx(embpath+'/dev.txt', len(devMentions), vectorsize, upto)
    input_hsngram_matrix[nsamples_train+nsamples_dev:totals] = load_embmatirx(embpath+'/test.txt', len(tstMentions), vectorsize, upto)
    print input_hsngram_matrix.shape
    srcname = 'hsngram' + emb_version
    hdf5_file += '_'+ srcname + '.h5py'
    f = h5py.File(hdf5_file, mode='w')
    features = f.create_dataset(srcname, input_hsngram_matrix.shape, dtype='float32')  # @UndefinedVariable
    features.attrs['vectorsize'] = vectorsize
    features[...] = input_hsngram_matrix
    features.dims[0].label = srcname + '_vector'
    split_dict = {
        'train': {srcname: (0, nsamples_train)},
        'dev': {srcname: (nsamples_train, nsamples_train + nsamples_dev)}, 
        'test': {srcname: (nsamples_train + nsamples_dev, totals)}}    
    f.attrs['split'] = H5PYDataset.create_split_array(split_dict)
    f.flush()
    f.close()
    logger.info('Building hinrich ngram-level embeddings of mentions finished. It saved in: %s', hdf5_file)

def build_typecosine_ds(trnMentions, devMentions, tstMentions, t2idx, hdf5_file, vectorfile, upto=-1):
    (embeddings, voc2idx, vectorsize) = read_embeddings(vectorfile, upto)
    totals = len(trnMentions) + len(devMentions) + len(tstMentions) 
    input_entvec = numpy.zeros(shape=(totals, vectorsize), dtype='float32')
    for i, men in enumerate(trnMentions + devMentions + tstMentions):
        mye = men.entityId
        entvec = numpy.zeros(vectorsize)
        if mye in voc2idx:
            entvec = embeddings[voc2idx[mye]]
        input_entvec[i] = entvec
    typevecmatrix = buildtypevecmatrix(t2idx, embeddings, vectorsize, voc2idx) # a matrix with size: 102 * dim
    ent_types_cosin_matrix = buildcosinematrix(input_entvec, typevecmatrix)
    logger.info(ent_types_cosin_matrix.shape)
    
    hdf5_file += '_tc.h5py'
    f = h5py.File(hdf5_file, mode='w')
    features = f.create_dataset('tc', ent_types_cosin_matrix.shape, dtype='float32')  # @UndefinedVariable
    features.attrs['vectorsize'] = ent_types_cosin_matrix.shape[1]
    features[...] = ent_types_cosin_matrix
    features.dims[0].label = 'types_ent_cosine'
    nsamples_train = len(trnMentions); nsamples_dev = len(devMentions);
    split_dict = {
        'train': {'tc': (0, nsamples_train)},
        'dev': {'tc': (nsamples_train, nsamples_train + nsamples_dev)}, 
        'test': {'tc': (nsamples_train + nsamples_dev, totals)}}    
    f.attrs['split'] = H5PYDataset.create_split_array(split_dict)
    f.flush()
    f.close()
    logger.info('Building types-ent cosine (tc) dataset finished. It saved in: %s', hdf5_file)


def build_targets_ds(trnMentions, devMentions, tstMentions, t2idx, dsdir):
    totals = len(trnMentions) + len(devMentions) + len(tstMentions) 
    targets_m = numpy.zeros(shape=(totals, len(t2idx)), dtype='int32')
    for i, men in enumerate(trnMentions + devMentions + tstMentions):
        types_idx = [t2idx[t] for t in men.alltypes] 
        targets_m[i] = cmn.convertTargetsToBinVec(types_idx, len(t2idx))
    hdf5_file = dsdir + '_targets.h5py'
    f = h5py.File(hdf5_file, mode='w')
    targets = f.create_dataset('targets', targets_m.shape, dtype='int32')
    targets.attrs['type_to_ix'] = yaml.dump(t2idx)
    targets[...] = targets_m
    targets.dims[0].label = 'all_types'
    nsamples_train = len(trnMentions); nsamples_dev = len(devMentions);
    split_dict = {
        'train': {'targets': (0, nsamples_train)},
        'dev': {'targets': (nsamples_train, nsamples_train + nsamples_dev)},
        'test': {'targets': (nsamples_train + nsamples_dev, totals)}}    
    f.attrs['split'] = H5PYDataset.create_split_array(split_dict)
    f.flush()
    f.close()

def main(args):
    print 'loading config file', args[1]
    config = cmn.loadConfig(args[1])
    dsdir = config['dsdir']
    #first generating name datasets based on the number of names for each set
    if not os.path.exists(os.path.join(dsdir,'train.txt')):
        generate_name_dataset(config) 
    
    trainfile = dsdir + '/train.txt'
    devfile = dsdir + '/dev.txt'
    testfile = dsdir + '/test.txt'
    targetTypesFile=config['typefile']
    vectorFile = config['ent_vectors']
#     the_features = config['features'].split(' ') #i.e. letters entvec words tc 
    ngrams = [int(n) for n in config['ngrams_n'].split()] if 'ngrams_n' in config else []
    ngrams_vecfiles = {ngram: config['ngrams'+str(ngram)+'_vecfile'] for ngram in ngrams}
    letter_vecfile = config['letters_vecfile'] if 'letters_vecfile' in config else None
    hs_ngram_path = config['hsngramvec'] if 'hsngramvec' in config else None
    
    upto = -1
    (t2idx, _) = cmn.loadtypes(targetTypesFile)
    trnMentions = load_ent_ds(trainfile)
    devMentions = load_ent_ds(devfile)
    tstMentions = load_ent_ds(testfile)
    logger.info("#train : %d #dev : %d #test : %d", len(trnMentions), len(devMentions), len(tstMentions))
    
    if True:
        build_targets_ds(trnMentions, devMentions, tstMentions, t2idx, dsdir)
        build_entvec_ds(trnMentions, devMentions, tstMentions, t2idx, dsdir, vectorFile, upto=-1)
        build_letters_ds(trnMentions, devMentions, tstMentions, t2idx, dsdir, letter_vecfile, max_len_name=40)
        build_typecosine_ds(trnMentions, devMentions, tstMentions, t2idx, dsdir, vectorFile, upto=-1)
        build_words_ds(trnMentions, devMentions, tstMentions, t2idx, dsdir, vectorFile, upto=-1)
        build_hsNgram_ds(config, trnMentions, devMentions, tstMentions, t2idx, dsdir, hs_ngram_path, vectorsize=300, upto=-1)
        for ng in ngrams:
            build_ngram_ds(trnMentions, devMentions, tstMentions, t2idx, dsdir, ngrams_vecfiles[ng], ng, upto=-1)
    else:
        if 'hsngramvec':
            build_hsNgram_ds(config, trnMentions, devMentions, tstMentions, t2idx, dsdir, hs_ngram_path, vectorsize=300, upto=-1)
        
if __name__ == '__main__':
    main(sys.argv)
    
        
    
    
