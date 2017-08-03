import os
import argparse
import json
import math
import shutil
import json
import time
from pprint import pprint

import tensorflow as tf
from tqdm import tqdm
import numpy as np
# CMG from IPython import embed
from basic.evaluator import F1Evaluator, Evaluator, ForwardEvaluator, MultiGPUF1Evaluator
from basic.graph_handler import GraphHandler
from basic.model import Model, get_multi_gpu_models
from basic.trainer import Trainer, MultiGPUTrainer

from basic.main import set_dirs
from basic.read_data import load_metadata, read_data, get_squad_data_filter, update_config

flags = tf.app.flags

# Names and directories
flags.DEFINE_string("model_name", "basic", "Model name [basic]")
flags.DEFINE_string("data_dir", "data/squad", "Data dir [data/squad]")
flags.DEFINE_string("run_id", "0", "Run ID [0]")
flags.DEFINE_string("out_base_dir", "out", "out base dir [out]")
flags.DEFINE_string("forward_name", "single", "Forward name [single]")
flags.DEFINE_string("answer_path", "", "Answer path []")
flags.DEFINE_string("eval_path", "", "Eval path []")
flags.DEFINE_string("load_path", "", "Load path []")
flags.DEFINE_string("shared_path", "", "Shared path []")

# Device placement
flags.DEFINE_string("device", "/cpu:0", "default device for summing gradients. [/cpu:0]")
flags.DEFINE_string("device_type", "gpu", "device for computing gradients (parallelization). cpu | gpu [gpu]")
flags.DEFINE_integer("num_gpus", 1, "num of gpus or cpus for computing gradients [1]")

# Essential training and test options
flags.DEFINE_string("mode", "test", "trains | test | forward [test]")
flags.DEFINE_boolean("load", True, "load saved data? [True]")
flags.DEFINE_bool("single", False, "supervise only the answer sentence? [False]")
flags.DEFINE_boolean("debug", False, "Debugging mode? [False]")
flags.DEFINE_bool('load_ema', True, "load exponential average of variables when testing?  [True]")
flags.DEFINE_bool("eval", True, "eval? [True]")
flags.DEFINE_bool("wy", False, "Use wy for loss / eval? [False]")
flags.DEFINE_bool("na", False, "Enable no answer strategy and learn bias? [False]")
flags.DEFINE_float("th", 0.5, "Threshold [0.5]")

# Training / test parameters
flags.DEFINE_integer("batch_size", 60, "Batch size [60]")
flags.DEFINE_integer("val_num_batches", 100, "validation num batches [100]")
flags.DEFINE_integer("test_num_batches", 0, "test num batches [0]")
flags.DEFINE_integer("num_epochs", 12, "Total number of epochs for training [12]")
flags.DEFINE_integer("num_steps", 20000, "Number of steps [20000]")
flags.DEFINE_integer("load_step", 0, "load step [0]")
flags.DEFINE_float("init_lr", 0.001, "Initial learning rate [0.001]")
flags.DEFINE_float("input_keep_prob", 0.8, "Input keep prob for the dropout of LSTM weights [0.8]")
flags.DEFINE_float("keep_prob", 0.8, "Keep prob for the dropout of Char-CNN weights [0.8]")
flags.DEFINE_float("wd", 0.0, "L2 weight decay for regularization [0.0]")
flags.DEFINE_integer("hidden_size", 100, "Hidden size [100]")
flags.DEFINE_integer("char_out_size", 100, "char-level word embedding size [100]")
flags.DEFINE_integer("char_emb_size", 8, "Char emb size [8]")
flags.DEFINE_string("out_channel_dims", "100", "Out channel dims of Char-CNN, separated by commas [100]")
flags.DEFINE_string("filter_heights", "5", "Filter heights of Char-CNN, separated by commas [5]")
flags.DEFINE_bool("finetune", False, "Finetune word embeddings? [False]")
flags.DEFINE_bool("highway", True, "Use highway? [True]")
flags.DEFINE_integer("highway_num_layers", 2, "highway num layers [2]")
flags.DEFINE_bool("share_cnn_weights", True, "Share Char-CNN weights [True]")
flags.DEFINE_bool("share_lstm_weights", True, "Share pre-processing (phrase-level) LSTM weights [True]")
flags.DEFINE_float("var_decay", 0.999, "Exponential moving average decay for variables [0.999]")

# Optimizations
flags.DEFINE_bool("cluster", False, "Cluster data for faster training [False]")
flags.DEFINE_bool("len_opt", False, "Length optimization? [False]")
flags.DEFINE_bool("cpu_opt", False, "CPU optimization? GPU computation can be slower [False]")

# Logging and saving options
flags.DEFINE_boolean("progress", True, "Show progress? [True]")
flags.DEFINE_integer("log_period", 100, "Log period [100]")
flags.DEFINE_integer("eval_period", 1000, "Eval period [1000]")
flags.DEFINE_integer("save_period", 1000, "Save Period [1000]")
flags.DEFINE_integer("max_to_keep", 20, "Max recent saves to keep [20]")
flags.DEFINE_bool("dump_eval", True, "dump eval? [True]")
flags.DEFINE_bool("dump_answer", True, "dump answer? [True]")
flags.DEFINE_bool("vis", False, "output visualization numbers? [False]")
flags.DEFINE_bool("dump_pickle", True, "Dump pickle instead of json? [True]")
flags.DEFINE_float("decay", 0.9, "Exponential moving average decay for logging values [0.9]")

# Thresholds for speed and less memory usage
flags.DEFINE_integer("word_count_th", 10, "word count th [100]")
flags.DEFINE_integer("char_count_th", 50, "char count th [500]")
flags.DEFINE_integer("sent_size_th", 400, "sent size th [64]")
flags.DEFINE_integer("num_sents_th", 8, "num sents th [8]")
flags.DEFINE_integer("ques_size_th", 30, "ques size th [32]")
flags.DEFINE_integer("word_size_th", 16, "word size th [16]")
flags.DEFINE_integer("para_size_th", 256, "para size th [256]")

# Advanced training options
flags.DEFINE_bool("lower_word", True, "lower word [True]")
flags.DEFINE_bool("squash", False, "squash the sentences into one? [False]")
flags.DEFINE_bool("swap_memory", True, "swap memory? [True]")
flags.DEFINE_string("data_filter", "max", "max | valid | semi [max]")
flags.DEFINE_bool("use_glove_for_unk", True, "use glove for unk [False]")
flags.DEFINE_bool("known_if_glove", True, "consider as known if present in glove [False]")
flags.DEFINE_string("logit_func", "tri_linear", "logit func [tri_linear]")
flags.DEFINE_string("answer_func", "linear", "answer logit func [linear]")
flags.DEFINE_string("sh_logit_func", "tri_linear", "sh logit func [tri_linear]")

# Ablation options
flags.DEFINE_bool("use_char_emb", True, "use char emb? [True]")
flags.DEFINE_bool("use_word_emb", True, "use word embedding? [True]")
flags.DEFINE_bool("q2c_att", True, "question-to-context attention? [True]")
flags.DEFINE_bool("c2q_att", True, "context-to-question attention? [True]")
flags.DEFINE_bool("dynamic_att", False, "Dynamic attention [False]")

class Demo(object):
    def __init__(self):
        config = flags.FLAGS
        config.out_dir = os.path.join(config.out_base_dir, config.model_name, str(config.run_id).zfill(2))
        config.max_sent_size = config.sent_size_th
        config.max_num_sents = config.num_sents_th
        config.max_ques_size = config.ques_size_th
        config.max_word_size = config.word_size_th
        config.max_para_size = config.para_size_th

        self.config = config
        self.test_data = None
        self.data_ready(update=True)  # That's if we were reading in preset demo data

        config = self.config

        set_dirs(config)
        models = get_multi_gpu_models(config)
        self.evaluator = ForwardEvaluator(config, models[0], tensor_dict=models[0].tensor_dict if config.vis else None)
        print("Creating Demo object: " + time.strftime("%H:%M:%S"))

        self.sess = tf.Session(config=tf.ConfigProto(allow_soft_placement=True))
        self.graph_handler = GraphHandler(config, models[0])
        self.graph_handler.initialize(self.sess)
        self.config = config

    def data_ready(self, data=None, update=False):
        
        config = self.config
        config.batch_size = 1
        test_data = read_data(self.config, 'demo', True, data=data, data_set=self.test_data)

        if update:
            update_config(self.config, [test_data])
            if config.use_glove_for_unk:
                word2vec_dict = test_data.shared['lower_word2vec'] if config.lower_word else test_data.shared['word2vec']
                new_word2idx_dict = test_data.shared['new_word2idx']
                idx2vec_dict = {idx: word2vec_dict[word] for word, idx in new_word2idx_dict.items()}
                new_emb_mat = np.array([idx2vec_dict[idx] for idx in range(len(idx2vec_dict))], dtype='float32')
                config.new_emb_mat = new_emb_mat
        self.config = config
        self.test_data = test_data
        print("data_ready at " + time.strftime("%H:%M:%S"))

    def run(self, data):
        self.data_ready(data=data)
        test_data = self.test_data
        config = self.config
        e = None
        print("\nCMG: Before get_batches")
        for multi_batch in test_data.get_batches(config.batch_size, num_batches=1, cluster=config.cluster):
            ei = self.evaluator.get_evaluation(self.sess, multi_batch)
            e = ei if e is None else e + ei
        print("\n\nCMG at {} e.id2answer_dict: {}".format(time.strftime("%H:%M:%S"), json.dumps(e.id2answer_dict)))
        return (e.id2answer_dict[0])

if __name__ == "__main__":
    tf.app.run()
