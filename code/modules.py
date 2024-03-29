# Copyright 2018 Stanford University
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""This file contains some basic model components"""

import argparse
import sys

import numpy as np
import tensorflow as tf
from tensorflow.python.ops.rnn_cell import DropoutWrapper, MultiRNNCell
from tensorflow.python.ops import variable_scope as vs
from tensorflow.python.ops import rnn_cell
from tensorflow.contrib.cudnn_rnn.python.ops import cudnn_rnn_ops

class biRNN(object):

    def __init__(self, hidden_size, batch_size, keep_prob, n_encoder_layers, use_cudnn):

        self.hidden_size = hidden_size
        self.batch_size = batch_size
        self.keep_prob = keep_prob
        self.n_encoder_layers = n_encoder_layers # needs more investigation
        self.use_cudnn = use_cudnn

        # differet in dropout
        if self.use_cudnn:
            self.rnn_fw = tf.contrib.cudnn_rnn.CudnnGRU(num_layers = self.n_encoder_layers, 
                          num_units = self.hidden_size, input_size = self.hidden_size)
            self.rnn_bw = tf.contrib.cudnn_rnn.CudnnGRU(num_layers = self.n_encoder_layers, 
                          num_units = self.hidden_size, input_size = self.hidden_size)
        else:
            self.rnn_cell_fw = DropoutWrapper(rnn_cell.LSTMCell(self.hidden_size), 
                               input_keep_prob = self.keep_prob)
            self.rnn_cell_bw = DropoutWrapper(rnn_cell.LSTMCell(self.hidden_size), 
                               input_keep_prob = self.keep_prob)
            """
            self.rnn_cell_fw = DropoutWrapper(cudnn_rnn_ops.CudnnCompatibleGRUCell(self.hidden_size), 
                               input_keep_prob = self.keep_prob)
            self.rnn_cell_bw = DropoutWrapper(cudnn_rnn_ops.CudnnCompatibleGRUCell(self.hidden_size), 
                               input_keep_prob = self.keep_prob)
            self.single_cell_fw = lambda: tf.contrib.cudnn_rnn.CudnnCompatibleGRUCell(self.hidden_size)
            self.rnn_cell_fw = tf.nn.rnn_cell.MultiRNNCell( 
                               [self.single_cell_fw() for _ in range(self.n_encoder_layers)])
            self.single_cell_bw = lambda: tf.contrib.cudnn_rnn.CudnnCompatibleGRUCell(self.hidden_size)
            self.rnn_cell_bw = tf.nn.rnn_cell.MultiRNNCell( 
                               [self.single_cell_bw() for _ in range(self.n_encoder_layers)])
            """

    def build_graph(self, inputs, masks, init_fw, init_bw):
        """
        Inputs:
          inputs: (batch_size, seq_len, input_size)
           masks: (batch_size, seq_len).

        Returns:
             out: (batch_size, seq_len, hidden_size*2).
        """
        with vs.variable_scope("biRNN"):
            input_lens = tf.cast(tf.reduce_sum(masks, reduction_indices=1), tf.int32) # shape (batch_size)

            if self.use_cudnn:

                inputs_fw = tf.transpose(inputs, [1, 0, 2])
                init_fw = tf.Variable(tf.zeros([1, 1, self.hidden_size]))
                init_fw = tf.tile(init_fw, [1, tf.shape(inputs_fw)[1], 1])
                param_fw = tf.Variable(tf.random_uniform([self.rnn_fw.params_size()], -0.1, 0.1), 
                                       validate_shape=False)
                fw_out, _ = self.rnn_fw(inputs_fw, init_fw, param_fw)
    
                # (seq_len, batch_size, input_size)
                inputs_bw = tf.reverse_sequence(inputs_fw, seq_lengths=input_lens,
                                                seq_dim = 0, batch_dim = 1)
    
                init_bw  = tf.Variable(tf.zeros([1, 1, self.hidden_size]))
                init_bw = tf.tile(init_bw, [1, tf.shape(inputs_bw)[1], 1])
                param_bw = tf.Variable(tf.random_uniform([self.rnn_bw.params_size()], -0.1, 0.1), 
                                       validate_shape=False)
                bw_out, _ = self.rnn_bw(inputs_bw, init_bw, param_bw)
    
                bw_out = tf.reverse_sequence(bw_out, seq_lengths=input_lens,
                                             seq_dim = 0, batch_dim = 1)

                # (batch_size, seq_len, input_size)
                fw_out = tf.transpose(fw_out, [1, 0, 2])
                bw_out = tf.transpose(bw_out, [1, 0, 2])

            else:

                # each is shape (batch_size, seq_len, hidden_size).
                (fw_out, bw_out), (final_fw, final_bw) = tf.nn.bidirectional_dynamic_rnn(
                                                         self.rnn_cell_fw, self.rnn_cell_bw, 
                                                         inputs, input_lens, init_fw, init_bw, 
                                                         dtype=tf.float32)

            # Concatenate the forward and backward hidden states
            out = tf.concat([fw_out, bw_out], 2)

            # Apply dropout
            out = tf.nn.dropout(out, self.keep_prob)

            return out, final_fw, final_bw


class uniRNN(object):

    def __init__(self, hidden_size, batch_size, keep_prob, use_cudnn):

        self.hidden_size = hidden_size
        self.batch_size = batch_size
        self.keep_prob = keep_prob
        self.use_cudnn = use_cudnn

        # differet in dropout 
        if self.use_cudnn:
            self.rnn = tf.contrib.cudnn_rnn.CudnnGRU(num_layers = 1, 
                       num_units  = self.hidden_size, 
                       input_size = self.hidden_size)
        else:
            self.rnn_cell = DropoutWrapper(rnn_cell.LSTMCell(self.hidden_size), 
                            input_keep_prob = self.keep_prob)
            """
            self.rnn_cell = DropoutWrapper(cudnn_rnn_ops.CudnnCompatibleGRUCell(self.hidden_size), 
                            input_keep_prob = self.keep_prob)
            self.single_cell = lambda: tf.contrib.cudnn_rnn.CudnnCompatibleGRUCell(self.hidden_size)
            self.rnn_cell = tf.nn.rnn_cell.MultiRNNCell( [self.single_cell() for _ in range(1)])
            """

    def build_graph(self, inputs, masks):
        """
        Inputs:
          inputs: (batch_size, seq_len, input_size)
          masks : (batch_size, seq_len)

        Returns:
             out: (batch_size, seq_len, hidden_size)
        """
        with vs.variable_scope("uniRNN"):
            input_lens = tf.cast(tf.reduce_sum(masks, reduction_indices=1), tf.int32) # shape (batch_size)

            if self.use_cudnn:

                # (seq_len, batch_size, input_size)
                inputs = tf.transpose(inputs, [1, 0, 2])
    
                init = tf.Variable(tf.zeros([1, 1, self.hidden_size]))
                init = tf.tile(init, [1, tf.shape(inputs)[1], 1])
                param = tf.Variable(tf.random_uniform([self.rnn.params_size()], -0.1, 0.1), 
                                    validate_shape=False)
                out, _ = self.rnn(inputs, init, param)
    
                # (batch_size, seq_len, input_size)
                out = tf.transpose(out, [1, 0, 2])

            else:

                # (batch_size, seq_len, hidden_size).
                out, _ = tf.nn.dynamic_rnn(self.rnn_cell, inputs, input_lens, dtype=tf.float32)

            # Apply dropout
            out = tf.nn.dropout(out, self.keep_prob)

            return out


class SimpleSoftmaxLayer(object):
    """
    Module to take set of hidden states, (e.g. one for each context location),
    and return probability distribution over those states.
    """

    def __init__(self):
        pass

    def build_graph(self, inputs, masks):
        """
        Applies one linear downprojection layer, then softmax.

        Inputs:
          inputs: Tensor shape (batch_size, seq_len, hidden_size)
          masks: Tensor shape (batch_size, seq_len)
            Has 1s where there is real input, 0s where there's padding.

        Outputs:
          logits: Tensor shape (batch_size, seq_len)
            logits is the result of the downprojection layer, but it has -1e30
            (i.e. very large negative number) in the padded locations
          prob_dist: Tensor shape (batch_size, seq_len)
            The result of taking softmax over logits.
            This should have 0 in the padded locations, and the rest should sum to 1.
        """
        with vs.variable_scope("SimpleSoftmaxLayer"):

            # Linear downprojection layer
            logits = tf.contrib.layers.fully_connected(inputs, num_outputs=1, activation_fn=None) # shape (batch_size, seq_len, 1)
            logits = tf.squeeze(logits, axis=[2]) # shape (batch_size, seq_len)

            # Take softmax over sequence
            masked_logits, prob_dist = masked_softmax(logits, masks, 1)

            return masked_logits, prob_dist


class AnswerPointerLayerStart(object):

    def __init__(self, keep_prob, hidden_size, value_vec_size):
        self.keep_prob = keep_prob
        self.hidden_size = hidden_size
        self.value_vec_size = value_vec_size

    def build_graph(self, questions, questions_mask, contexts, contexts_mask):

        with vs.variable_scope("AnswerPointerLayerStart"):

            ###### start answer pooling ######

            Vrq = tf.get_variable("v_answer_pooling", shape=[1, self.hidden_size*2], 
                  initializer=tf.contrib.layers.xavier_initializer())

            # (hidden_size*2, 1)
            k = tf.layers.dense(Vrq, self.hidden_size*2, activation=tf.nn.relu, use_bias=False, name="Wvrq")
            # (batch_size, question_len, hidden_size*2)
            # v = tf.layers.dense(questions, self.hidden_size*2, activation=tf.nn.relu, use_bias=False, name="Wv")
            v = questions

            # (batch_size * question_len, hidden_size*2)
            v_flat = tf.reshape(v, [-1, self.hidden_size*2])
            # (hidden_size*2, batch_size * question_len)
            v_t = tf.transpose(v_flat) 
            # (1, batch_size * question_len)
            attn_logits_flat = tf.matmul(k, v_t / np.sqrt(self.hidden_size*2))
            # (batch_size, 1, question_len)
            attn_logits = tf.reshape(attn_logits_flat, [tf.shape(v)[0], 1, tf.shape(v)[1]])

            attn_logits_mask = tf.expand_dims(questions_mask, 1) # shape (batch_size, 1, num_questions)
            _, attn_dist = masked_softmax(attn_logits, attn_logits_mask, 2) # shape (batch_size, 1, num_questions)

            rQ = tf.matmul(attn_dist, v) # (batch_size, 1, hidden_size*2)

            ###### end answer pooling ######

            # (batch_size, 1, value_vec_size)
            # the dimenson of rQ will go from hidden_size*2 to value_vec_size
            k1 = tf.layers.dense(rQ, self.value_vec_size, activation=tf.nn.relu, use_bias=False, name="Wrq")
            #print "k1 shape: " + str(k1.get_shape())
            # (batch_size, context_len, value_vec_size)
            # v1 = tf.layers.dense(contexts, self.value_vec_size, activation=tf.nn.relu, use_bias=False, name="Wp")
            v1 = contexts
            #print "v1 shape: " + str(v1.get_shape())
            # (batch_size, value_vec_size, context_len)
            v1_t = tf.transpose(v1, perm=[0, 2, 1]) 

            # (batch_size, 1, context_len)
            attn_logits1 = tf.matmul(k1, v1_t / np.sqrt(self.value_vec_size))
            # (batch_size, context_len)
            squeezed_attn_logits1 = tf.squeeze(attn_logits1, axis=[1]) 
            # (batch_size, context_len)
            masked_logits1, prob_dist = masked_softmax(squeezed_attn_logits1, contexts_mask, 1) 

            return rQ, masked_logits1, prob_dist


class AnswerPointerLayerEnd(object):

    def __init__(self, keep_prob, hidden_size, value_vec_size):
        self.keep_prob = keep_prob
        self.hidden_size = hidden_size
        self.value_vec_size = value_vec_size
        self.rnn_cell = rnn_cell.GRUCell(self.hidden_size*2)

    def build_graph(self, prob_dist, init_hidden_state, contexts, contexts_mask):

        with vs.variable_scope("AnswerPointerLayerEnd"):

            ###### start pointer rnn ######

            # (batch_size, 1, context_len)
            expanded_prob_dist = tf.expand_dims(prob_dist, 1) 
            # (batch_size, 1, value_vec_size)
            inputs = tf.matmul(expanded_prob_dist, contexts)
            # (batch_size, 1, hidden_size*2)
            # (batch_size, hidden_size*2)
            squeezed_init_hidden_state = tf.squeeze(init_hidden_state, axis=[1]) 
            _, final_state = tf.nn.dynamic_rnn(self.rnn_cell, inputs, 
                             initial_state=squeezed_init_hidden_state, dtype=tf.float32)

            ###### end pointer rnn ######

            # (batch_size, 1, hidden_size*2)
            expanded_final_state = tf.expand_dims(final_state, 1)
            # (batch_size, 1, value_vec_size)
            k1 = tf.layers.dense(expanded_final_state, self.value_vec_size, 
                                 activation=tf.nn.relu, use_bias=False, name="Wrq")
            # (batch_size, context_len, value_vec_size)
            # v1 = tf.layers.dense(contexts, self.value_vec_size, activation=tf.nn.relu, use_bias=False, name="Wp")
            v1 = contexts
            # (batch_size, value_vec_size, context_len)
            v1_t = tf.transpose(v1, perm=[0, 2, 1]) 

            # (batch_size, 1, context_len)
            attn_logits1 = tf.matmul(k1, v1_t / np.sqrt(self.value_vec_size))
            # (batch_size, context_len)
            squeezed_attn_logits1 = tf.squeeze(attn_logits1, axis=[1]) 
            # (batch_size, context_len)
            masked_logits1, prob_dist = masked_softmax(squeezed_attn_logits1, contexts_mask, 1) 

            return masked_logits1, prob_dist


class BasicAttn(object):
    """Module for basic attention.

    Note: in this module we use the terminology of "keys" and "values" (see lectures).
    In the terminology of "X attends to Y", "keys attend to values".

    In the baseline model, the keys are the context hidden states
    and the values are the question hidden states.

    We choose to use general terminology of keys and values in this module
    (rather than context and question) to avoid confusion if you reuse this
    module with other inputs.
    """

    def __init__(self, keep_prob, key_vec_size, value_vec_size, advanced_basic_attn):
        """
        Inputs:
          keep_prob: tensor containing a single scalar that is the keep probability (for dropout)
          key_vec_size: size of the key vectors. int
          value_vec_size: size of the value vectors. int
        """
        self.keep_prob = keep_prob
        self.key_vec_size = key_vec_size
        self.value_vec_size = value_vec_size
        self.advanced_basic_attn = advanced_basic_attn

    def build_graph(self, values, values_mask, keys):
        """
        Keys attend to values.
        For each key, return an attention distribution and an attention output vector.

        Inputs:
          values: Tensor shape (batch_size, num_values, value_vec_size).
          values_mask: Tensor shape (batch_size, num_values).
            1s where there's real input, 0s where there's padding
          keys: Tensor shape (batch_size, num_keys, value_vec_size)

        Outputs:
          attn_dist: Tensor shape (batch_size, num_keys, num_values).
            For each key, the distribution should sum to 1,
            and should be 0 in the value locations that correspond to padding.
          output: Tensor shape (batch_size, num_keys, hidden_size).
            This is the attention output; the weighted sum of the values
            (using the attention distribution as weights).
        """
        with vs.variable_scope("BasicAttn"):

            if self.advanced_basic_attn:
                k = tf.layers.dense(keys, self.key_vec_size, activation=tf.nn.relu, use_bias=False, name="Wk")
                # v = tf.layers.dense(values, self.value_vec_size, activation=tf.nn.relu, use_bias=False, name="Wv")
                v = values
            else:
                k = keys
                v = values

            # Calculate attention distribution
            values_t = tf.transpose(v, perm=[0, 2, 1]) # (batch_size, value_vec_size, num_values)

            if self.advanced_basic_attn:
                attn_logits = tf.matmul(k, values_t / np.sqrt(self.value_vec_size))
            else:
                attn_logits = tf.matmul(k, values_t) # shape (batch_size, num_keys, num_values)

            attn_logits_mask = tf.expand_dims(values_mask, 1) # shape (batch_size, 1, num_values)
            _, attn_dist = masked_softmax(attn_logits, attn_logits_mask, 2) # shape (batch_size, num_keys, num_values). take softmax over values

            # Use attention distribution to take weighted sum of values
            output = tf.matmul(attn_dist, values) # shape (batch_size, num_keys, value_vec_size)

            # Apply dropout
            output = tf.nn.dropout(output, self.keep_prob)

            return attn_dist, output


class biDAF(object):

    def __init__(self, keep_prob, value_vec_size):

        self.keep_prob = keep_prob
        self.value_vec_size = value_vec_size

    def build_graph(self, questions, questions_mask, contexts, contexts_mask):

        with vs.variable_scope("biDAF"):

            # (batch_size, context_len, 1)
            c = tf.layers.dense(contexts, 1, activation=None, use_bias=False, name="Wsim_c")
            #print "shape c: " + str(c.get_shape())
            # (batch_size, question_len, 1)
            q = tf.layers.dense(questions, 1, activation=None, use_bias=False, name="Wsim_q")
            #print "shape q: " + str(q.get_shape())

            w = tf.get_variable("Wsim_cq", shape=[1, 1, self.value_vec_size], 
                initializer=tf.contrib.layers.xavier_initializer())
            # (batch_size, context_len, value_vec_size)
            cw = tf.multiply(contexts, w)
            #print "shape cw: " + str(cw.get_shape())
            # cw: (batch_size, context_len, value_vec_size)
            # questions: (batch_size, question_len, value_vec_size)
            # (batch_size, value_vec_size, question_len)
            questions_t = tf.transpose(questions, perm=[0, 2, 1])
            # (batch_size, context_len, question_len)
            cq = tf.matmul(cw, questions_t)
            #print "shape cq: " + str(cq.get_shape())

            # (batch_size, 1, question_len)
            q_t = tf.transpose(q, perm=[0, 2, 1]) 
            # (batch_size, context_len, question_len)
            S = c + q_t + cq
            #print "shape S: " + str(S.get_shape())

            # (batch_size, 1, question_len)
            attn_questions_mask = tf.expand_dims(questions_mask, 1) 
            # (batch_size, context_len, question_len)
            _, attn_question_dist = masked_softmax(S, attn_questions_mask, 2) 

            # (batch_size, context_len, value_vec_size)
            A = tf.matmul(attn_question_dist, questions) 

            # (batch_size, context_len)
            m = tf.reduce_max(S, axis=2)
            # (batch_size, context_len)
            _, attn_context_dist = masked_softmax(m, contexts_mask, 1) 

            # (batch_size, 1, context_len)
            attn_context_dist_exp = tf.expand_dims(attn_context_dist, 1) 
            # (batch_size, 1, value_vec_size)
            c_p = tf.matmul(attn_context_dist_exp, contexts)

            # (batch_size, context_len, hidden_size * 8)
            output = tf.concat([contexts, A, contexts * A, contexts * c_p], 2)

            # Apply dropout
            output = tf.nn.dropout(output, self.keep_prob)

            return output


class SelfAttn(object):
    """
    Module for self attention.
    """

    def __init__(self, keep_prob, value_vec_size):
        """
        Inputs:
          keep_prob: tensor containing a single scalar that is the keep probability (for dropout)
          value_vec_size: size of the value vectors. int
        """
        self.keep_prob = keep_prob
        self.value_vec_size = value_vec_size

    def build_graph(self, values, values_mask):
        """
        Keys attend to values.
        For each key, return an attention distribution and an attention output vector.

        Inputs:
          values: Tensor shape (batch_size, num_values, value_vec_size).
          values_mask: Tensor shape (batch_size, num_values).
            1s where there's real input, 0s where there's padding
          keys: Tensor shape (batch_size, num_keys, value_vec_size)

        Outputs:
          attn_dist: Tensor shape (batch_size, num_keys, num_values).
            For each key, the distribution should sum to 1,
            and should be 0 in the value locations that correspond to padding.
          output: Tensor shape (batch_size, num_keys, hidden_size).
            This is the attention output; the weighted sum of the values
            (using the attention distribution as weights).
        """
        with vs.variable_scope("SelfAttn"):

            # source_sequence_length = tf.reduce_sum(values_mask, reduction_indices = 1)
            v1 = tf.layers.dense(values, self.value_vec_size, use_bias=False)
            # v2 = tf.layers.dense(values, self.value_vec_size, use_bias=False)
            v2 = values

            v = tf.get_variable("v_attention", shape=[self.value_vec_size], 
                initializer=tf.contrib.layers.xavier_initializer())

            reshaped_v1 = tf.expand_dims(v1, 1)
            reshaped_v2 = tf.expand_dims(v2, 2)

            self_attn_logits = tf.reduce_sum(v * tf.tanh(reshaped_v1 + reshaped_v2), 3)

            self_attn_logits_mask = tf.expand_dims(values_mask, 1) # (batch_size, 1, num_values)
            _, self_attn_dist = masked_softmax(self_attn_logits, self_attn_logits_mask, 2) # (batch_size, num_values, num_values)

            # Use attention distribution to take weighted sum of values
            output = tf.matmul(self_attn_dist, values) # shape (batch_size, num_values, value_vec_size)

            # Apply dropout
            # output = tf.nn.dropout(output, self.keep_prob)

            return self_attn_dist, output


class DotAttn(object):
    """
    Module for dot attention.
    """

    def __init__(self, keep_prob, value_vec_size, advanced_dot_attn):
        """
        Inputs:
          keep_prob: tensor containing a single scalar that is the keep probability (for dropout)
          value_vec_size: size of the value vectors. int
        """
        self.keep_prob = keep_prob
        self.value_vec_size = value_vec_size
        self.advanced_dot_attn = advanced_dot_attn

    def build_graph(self, values, values_mask):
        """
        Keys attend to values.
        For each key, return an attention distribution and an attention output vector.

        Inputs:
          values: Tensor shape (batch_size, num_values, value_vec_size).
          values_mask: Tensor shape (batch_size, num_values).
            1s where there's real input, 0s where there's padding
          keys: Tensor shape (batch_size, num_keys, value_vec_size)

        Outputs:
          attn_dist: Tensor shape (batch_size, num_keys, num_values).
            For each key, the distribution should sum to 1,
            and should be 0 in the value locations that correspond to padding.
          output: Tensor shape (batch_size, num_keys, hidden_size).
            This is the attention output; the weighted sum of the values
            (using the attention distribution as weights).
        """
        with vs.variable_scope("DotAttn"):

            if self.advanced_dot_attn:
                v1 = tf.layers.dense(values, self.value_vec_size, activation=tf.nn.relu, use_bias=False, name="W1")
                # v2 = tf.layers.dense(values, self.value_vec_size, activation=tf.nn.relu, use_bias=False, name="W2")
                v2 = values
            else:
                v1 = tf.layers.dense(values, self.value_vec_size, use_bias=False, name="W1")
                # v2 = tf.layers.dense(values, self.value_vec_size, use_bias=False, name="W2")
                v2 = values

            if self.advanced_dot_attn:
                self_attn_logits = tf.matmul(v1, 
                                   tf.transpose(v2, [0, 2, 1]) / np.sqrt(self.value_vec_size))
            else:
                self_attn_logits = tf.matmul(v1, tf.transpose(v2, [0, 2, 1]))

            self_attn_logits_mask = tf.expand_dims(values_mask, 1) # (batch_size, 1, num_values)
            _, self_attn_dist = masked_softmax(self_attn_logits, self_attn_logits_mask, 2) # (batch_size, num_values, num_values)

            # Use attention distribution to take weighted sum of values
            output = tf.matmul(self_attn_dist, values) # shape (batch_size, num_values, value_vec_size)

            # Apply dropout
            output = tf.nn.dropout(output, self.keep_prob)

            return self_attn_dist, output


class GatedReps(object):
    """
    Module for gated representation.
    """

    def __init__(self, value_vec_size):
        """
        Inputs:
          value_vec_size: size of the value vectors. int
        """
        self.value_vec_size = value_vec_size

    def build_graph(self, values):

        with vs.variable_scope("GatedReps"):

            # (batch_size * num_values, value_vec_size) * (value_vec_size, 1)
            # (batch_size * num_values, 1)
            # (batch_size, num_values, 1)
            gate = tf.contrib.layers.fully_connected(values, 
                   num_outputs = 1, activation_fn=tf.nn.sigmoid) 

            output = gate * values # (batch_size, num_values, value_vec_size)

            return output


def masked_softmax(logits, mask, dim):
    """
    Takes masked softmax over given dimension of logits.

    Inputs:
      logits: Numpy array. We want to take softmax over dimension dim.
      mask: Numpy array of same shape as logits.
        Has 1s where there's real data in logits, 0 where there's padding
      dim: int. dimension over which to take softmax

    Returns:
      masked_logits: Numpy array same shape as logits.
        This is the same as logits, but with 1e30 subtracted
        (i.e. very large negative number) in the padding locations.
      prob_dist: Numpy array same shape as logits.
        The result of taking softmax over masked_logits in given dimension.
        Should be 0 in padding locations.
        Should sum to 1 over given dimension.
    """
    exp_mask = (1 - tf.cast(mask, 'float')) * (-1e30) # -large where there's padding, 0 elsewhere
    masked_logits = tf.add(logits, exp_mask) # where there's padding, set logits to -large
    prob_dist = tf.nn.softmax(masked_logits, dim)
    return masked_logits, prob_dist

"""
def test_attn_pooling_layer():
    print "Test attn pooling layer:"
    with tf.Graph().as_default():
        with tf.variable_scope("test_attn_pooling_layer"):
            value_placeholder = tf.placeholder(tf.float32, shape=[1, 3, 2])
            value_mask_placeholder = tf.placeholder(tf.float32, shape=[1, 3])

            attn_pooling_layer = AttnPoolingLayer(1, 2)
            dist, attn_pooling_output = attn_pooling_layer.build_graph(value_placeholder, value_mask_placeholder) 
            print "attn pooling distribution shape = " + str(np.shape(dist))
            print "attn pooling output shape = " + str(np.shape(attn_pooling_output))
"""

def test_self_attn_layer():
    print "Test self attention layer:"
    with tf.Graph().as_default():
        with tf.variable_scope("test_self_attn_layer"):
            # key_placeholder is shape (batch_size, context_len, hidden_size*2)
            value_placeholder = tf.placeholder(tf.float32, shape=[1, 3, 2])
            value_mask_placeholder = tf.placeholder(tf.float32, shape=[1, 3])

            #tf.get_variable_scope().reuse_variables()
            self_attn_layer = SelfAttn(1, 2)
            dist, self_attn_output = self_attn_layer.build_graph(value_placeholder, value_mask_placeholder) 
            #print self_attn_output.get_shape()
            print "self attn distribution shape = " + str(np.shape(dist))
            print "self attn output shape = " + str(np.shape(self_attn_output))

def test_dot_attn_layer():
    print "Test dot attention layer:"
    with tf.Graph().as_default():
        with tf.variable_scope("test_dot_attn_layer"):
            value_placeholder = tf.placeholder(tf.float32, shape=[None, 3, 2]) # (batch_size, context_len, hidden_size*2)
            value_mask_placeholder = tf.placeholder(tf.float32, shape=[None, 3])

            with tf.variable_scope("DotAttn"):
                tf.get_variable("W1/kernel", initializer=np.array(np.eye(2,2), dtype=np.float32))
                tf.get_variable("W2/kernel", initializer=np.array(np.eye(2,2), dtype=np.float32))

            tf.get_variable_scope().reuse_variables()
            dot_attn_layer = DotAttn(1, 2, False) # (keep_prob, context_len, advanced_dot_attn)

            dist, dot_attn_output = dot_attn_layer.build_graph(value_placeholder, value_mask_placeholder) 
            print "Trainable variables: "
            print tf.trainable_variables()
            print "dot attn distribution shape = " + str(np.shape(dist))
            print "dot attn output shape = " + str(np.shape(dot_attn_output))

            init = tf.global_variables_initializer()
            with tf.Session() as session:
                session.run(init)
                v = np.array([
                    [[0.4,  0.5], # batch 0
                     [0.3, -0.2],
                     [0.6, -0.1]],
                    [[4, -5],     # batch 1
                     [8,  2],
                     [9, -1]]
                    ], dtype=np.float32)
                m = np.array([[1, 1, 0], # batch 0
                              [1, 0, 0]  # batch 1
                             ], dtype=np.float32)
                dist_, attn_ = session.run([dist, dot_attn_output], 
                               feed_dict={value_placeholder: v, value_mask_placeholder: m})
                print("\ndist_ = ")
                print dist_
                print("\nattn_ = ")
                print attn_
                expected_attn_ = np.array([
                    [[0.35962827, 0.21739789],  # batch 0
                     [0.34725277, 0.13076939],
                     [0.34975   , 0.14825001]],
                    [[4, -5],                   # batch 1
                     [4, -5],
                     [4, -5]]
                    ], dtype=np.float32)
                assert np.allclose(attn_, expected_attn_, atol=1e-2), "attention not correct"


def test_gated_reps_layer():
    print "Test gated reps layer:"
    with tf.Graph().as_default():
        with tf.variable_scope("test_gated_reps_layer"):
            value_placeholder = tf.placeholder(tf.float32, shape=[1, 3, 2])

            gated_reps_layer = GatedReps(2)
            output = gated_reps_layer.build_graph(value_placeholder) 
            print "gated reps output shape = " + str(np.shape(output))


def test_dot_rnn_layer():
    print "Test dot rnn layer:"
    with tf.Graph().as_default():
        with tf.variable_scope("test_dot_attn_layer"):
            # key_placeholder is shape (batch_size, context_len, hidden_size*2)
            value_placeholder = tf.placeholder(tf.float32, shape=[None, 3, 2])
            value_mask_placeholder = tf.placeholder(tf.float32, shape=[None, 3])

            dot_rnn_layer = biRNN(2, 4, 1, 1, True)
            output = dot_rnn_layer.build_graph(value_placeholder, value_mask_placeholder) 
            print "Trainable variables: "
            print tf.trainable_variables()
            print "dot rnn output shape = " + str(np.shape(output))

            init = tf.global_variables_initializer()
            with tf.Session() as session:
                session.run(init)
                v = np.array([
                    [[0.4,  0.5], # batch 0
                     [0.3, -0.2],
                     [0.6, -0.1]],
                    [[4, -5],     # batch 1
                     [8,  2],
                     [9, -1]]
                    ], dtype=np.float32)
                m = np.array([[1, 1, 0], # batch 0
                              [1, 0, 0]  # batch 1
                             ], dtype=np.float32)
                out_ = session.run(output, feed_dict={value_placeholder: v, value_mask_placeholder: m})
                print("\nout_ = ")
                print out_
                expected_attn_ = np.array([
                    [[0.35962827, 0.21739789],  # batch 0
                     [0.34725277, 0.13076939],
                     [0.34975   , 0.14825001]],
                    [[4, -5],                   # batch 1
                     [4, -5],
                     [4, -5]]
                    ], dtype=np.float32)
                #assert np.allclose(attn_, expected_attn_, atol=1e-2), "attention not correct"


def test_dense_layer():
    print "Test dense layer:"
    with tf.Graph().as_default():
        with tf.variable_scope("test_dense_layer"):
            value_placeholder = tf.placeholder(tf.float32, shape=[3, 2])

            v1 = tf.layers.dense(value_placeholder, 2, use_bias=False, name="W")
            loss = tf.reduce_sum(v1)
            print "dense layer output shape = " + str(np.shape(v1))
            print "loss shape = " + str(np.shape(loss))

            init = tf.global_variables_initializer()
            opt = tf.train.AdadeltaOptimizer()
            with tf.Session() as session:
                session.run(init)
                v = np.array(
                    [[4, -5],     # batch 0
                     [8,  2],
                     [9, -1]] , dtype=np.float32)
                out_ = session.run(loss, feed_dict={value_placeholder: v})
                print "Trainable variables: "
                print tf.trainable_variables()
                print("out_ = ")
                print out_
                #assert np.allclose(attn_, expected_attn_, atol=1e-2), "attention not correct"


def test_bidaf_layer():
    print "Test bidaf layer:"
    with tf.Graph().as_default():
        with tf.variable_scope("test_bidaf_layer"):
            question_placeholder = tf.placeholder(tf.float32, shape=[None, 3, 2])
            question_mask_placeholder = tf.placeholder(tf.float32, shape=[None, 3])
            context_placeholder = tf.placeholder(tf.float32, shape=[None, 4, 2])
            context_mask_placeholder = tf.placeholder(tf.float32, shape=[None, 4])

            bidaf_layer = biDAF(1, 2)
            output = bidaf_layer.build_graph(question_placeholder, 
                                             question_mask_placeholder,
                                             context_placeholder,
                                             context_mask_placeholder) 
            print "Trainable variables: "
            print tf.trainable_variables()
            print "bidaf output shape = " + str(np.shape(output))


def do_test(_):
    print "Testing starts:"
    #test_attn_pooling_layer()
    #test_self_attn_layer()
    #test_dot_attn_layer()
    #test_dot_rnn_layer()
    #test_dense_layer()
    test_bidaf_layer()
    #test_gated_reps_layer()
    print "Passed!"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Tests modules')
    subparsers = parser.add_subparsers()

    command_parser = subparsers.add_parser('test', help='')
    command_parser.set_defaults(func=do_test)

    ARGS = parser.parse_args()
    if ARGS.func is None:
        parser.print_help()
        sys.exit(1)
    else:
        ARGS.func(ARGS)

