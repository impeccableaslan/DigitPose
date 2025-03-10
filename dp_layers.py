from __future__ import print_function
from six.moves import xrange
from dp_batch import Batch
from dp_roipool import ROIPoolingLayer
from dp_shapematchloss import SLoss, SLoss_accuracy
from dp_labelsloss import weighted_PixelWise_CrossEntropy
import tensorflow as tf
import numpy as np
import TensorflowUtils as utils
import datetime
import scipy.io
import os
import pathlib
import cv2

class DP:
    def __init__(self, debug, n_classes, n_points, IMAGE_WH, model_dir):
        ''' Settings '''
        self.debug = debug
        self.n_classes = n_classes
        self.n_points = n_points
        self.IMAGE_WH = IMAGE_WH

        ''' VGG19 '''
        self.model_dir = model_dir

        ''' General variables '''
        self.image = tf.placeholder(tf.float32, shape=[None, IMAGE_WH, IMAGE_WH, 3], name="input_image")

        ''' Labels branch hyperparameters '''
        self.labels_learning_rate = 1e-4

        ''' Centers branch hyperparameters '''
        self.centers_learning_rate = 1e-4

        ''' Pose branch hyperparameters '''
        self.pose_learning_rate = 1e-4
        self.roi_pool_h = 7
        self.roi_pool_w = 7

        self.build_graph()
    
    def build_graph(self):
        """
        Semantic segmentation network definition
        :param image: input image. Should have values in range 0-255
        :param keep_prob:
        :return:
        """
        print("setting up vgg initialized conv layers ...")
        model_data = scipy.io.loadmat(self.model_dir)
        mean = model_data['normalization'][0][0][0]
        mean_pixel = np.mean(mean, axis=(0, 1))
        weights = np.squeeze(model_data['layers'])
        processed_image = utils.process_image(self.image, mean_pixel)
        self.image_net = self.vgg_net(weights, processed_image)
        self.vgg_fc = self.vgg_net_fc(weights)
        self.build_labels_branch()
        self.build_centers_branch()
        self.build_pose_branch()

    def build_labels_branch(self):
        self.labels_keep_probability = tf.placeholder(tf.float32, name="labels_keep_probabilty")
        self.labels_annotation = tf.placeholder(tf.int32, shape=[None, self.IMAGE_WH, self.IMAGE_WH, 1], name="labels_annotation")
        _, labels_logits = self.build_labels_layers(self.image, self.labels_keep_probability)
        labels_loss = tf.reduce_mean((tf.nn.sparse_softmax_cross_entropy_with_logits(logits=labels_logits,
                                                                              labels=tf.squeeze(self.labels_annotation, squeeze_dims=[3]),
                                                                              name="labels_entropy")))
        labels_loss_summary = tf.summary.scalar("labels_entropy", labels_loss)
        labels_trainable_var = tf.trainable_variables(scope="labels")
        if self.debug:
            for var in labels_trainable_var:
                utils.add_to_regularization_and_summary(var)
        self.labels_train_op = self.build_labels_optimizer(labels_loss, labels_trainable_var)
        self.labels_pred = tf.argmax(tf.nn.softmax(labels_logits, axis=-1), axis=-1, name="labels_pred")
        labels_pred_correct = tf.equal(self.labels_pred, tf.argmax(tf.squeeze(self.labels_annotation, squeeze_dims=[3]), -1), name="labels_pred_correct") 
        self.labels_pred_accuracy = tf.reduce_mean(tf.cast(labels_pred_correct, dtype=tf.float32), name="labels_pred_accuracy")

        print("Setting up labels summary op...")
        labels_summary_op = tf.summary.merge_all()
    
    def build_labels_layers(self, image, keep_prob):
        with tf.variable_scope("labels"):
            pool5 = utils.max_pool_2x2(self.image_net["conv5_3"])

            W6 = utils.weight_variable([7, 7, 512, 4096], name="W6")
            b6 = utils.bias_variable([4096], name="b6")
            conv6 = utils.conv2d_basic(pool5, W6, b6)
            relu6 = tf.nn.relu(conv6, name="relu6")
            if self.debug:
                utils.add_activation_summary(relu6)
            relu_dropout6 = tf.nn.dropout(relu6, keep_prob=keep_prob)

            W7 = utils.weight_variable([1, 1, 4096, 4096], name="W7")
            b7 = utils.bias_variable([4096], name="b7")
            conv7 = utils.conv2d_basic(relu_dropout6, W7, b7)
            relu7 = tf.nn.relu(conv7, name="relu7")
            if self.debug:
                utils.add_activation_summary(relu7)
            relu_dropout7 = tf.nn.dropout(relu7, keep_prob=keep_prob)

            W8 = utils.weight_variable([1, 1, 4096, self.n_classes], name="W8")
            b8 = utils.bias_variable([self.n_classes], name="b8")
            conv8 = utils.conv2d_basic(relu_dropout7, W8, b8)
            # annotation_pred1 = tf.argmax(conv8, dimension=3, name="prediction1")

            deconv_shape1 = self.image_net["pool4"].get_shape()
            W_t1 = utils.weight_variable([4, 4, deconv_shape1[3].value, self.n_classes], name="W_t1")
            b_t1 = utils.bias_variable([deconv_shape1[3].value], name="b_t1")
            conv_t1 = utils.conv2d_transpose_strided(conv8, W_t1, b_t1, output_shape=tf.shape(self.image_net["pool4"]))
            fuse_1 = tf.add(conv_t1, self.image_net["pool4"], name="fuse_1")

            deconv_shape2 = self.image_net["pool3"].get_shape()
            W_t2 = utils.weight_variable([4, 4, deconv_shape2[3].value, deconv_shape1[3].value], name="W_t2")
            b_t2 = utils.bias_variable([deconv_shape2[3].value], name="b_t2")
            conv_t2 = utils.conv2d_transpose_strided(fuse_1, W_t2, b_t2, output_shape=tf.shape(self.image_net["pool3"]))
            fuse_2 = tf.add(conv_t2, self.image_net["pool3"], name="fuse_2")

            shape = tf.shape(image)
            deconv_shape3 = tf.stack([shape[0], shape[1], shape[2], self.n_classes])
            W_t3 = utils.weight_variable([16, 16, self.n_classes, deconv_shape2[3].value], name="W_t3")
            b_t3 = utils.bias_variable([self.n_classes], name="b_t3")
            conv_t3 = utils.conv2d_transpose_strided(fuse_2, W_t3, b_t3, output_shape=deconv_shape3, stride=8)

            annotation_pred = tf.argmax(conv_t3, dimension=3, name="prediction")

        return tf.expand_dims(annotation_pred, dim=3), conv_t3

    def build_labels_optimizer(self, loss_val, var_list):
        with tf.variable_scope("labels"):
            labels_optimizer = tf.train.AdamOptimizer(self.labels_learning_rate)
            labels_grads = labels_optimizer.compute_gradients(loss_val, var_list=var_list)
            if self.debug:
                # print(len(var_list))
                for grad, var in labels_grads:
                    utils.add_gradient_summary(grad, var)
            return labels_optimizer.apply_gradients(labels_grads)

    def build_centers_branch(self):
        self.centers_keep_probability = tf.placeholder(tf.float32, name="centers_keep_probabilty")
        self.centers_annotation = tf.placeholder(tf.int32, shape=[None, self.IMAGE_WH, self.IMAGE_WH, 3 * (self.n_classes - 1)], name="centers_annotation")
        self.centers_pred = self.build_centers_layers(self.image, self.centers_keep_probability)
        centers_loss = tf.losses.huber_loss(labels=self.centers_annotation, predictions=self.centers_pred, weights=1.0, scope="centers")
        centers_loss_summary = tf.summary.scalar("centers_entropy", centers_loss)
        centers_trainable_var = tf.trainable_variables(scope="centers")
        if self.debug:
            for var in centers_trainable_var:
                utils.add_to_regularization_and_summary(var)
        self.centers_train_op = self.build_centers_optimizer(centers_loss, centers_trainable_var)
        centers_pred_correct = tf.equal(tf.cast(self.centers_pred, tf.float32), tf.cast(self.centers_annotation, tf.float32), name="centers_pred_correct") 
        self.centers_pred_accuracy = tf.reduce_mean(tf.cast(centers_pred_correct, dtype=tf.float32), name="centers_pred_accuracy")

        print("Setting up centers summary op...")
        centers_summary_op = tf.summary.merge_all()
    
    def build_centers_layers(self, image, keep_prob):
        with tf.variable_scope("centers"):
            pool5 = utils.max_pool_2x2(self.image_net["conv5_3"])

            W6 = utils.weight_variable([7, 7, 512, 4096], name="W6")
            b6 = utils.bias_variable([4096], name="b6")
            conv6 = utils.conv2d_basic(pool5, W6, b6)
            relu6 = tf.nn.relu(conv6, name="relu6")
            if self.debug:
                utils.add_activation_summary(relu6)
            relu_dropout6 = tf.nn.dropout(relu6, keep_prob=keep_prob)

            W7 = utils.weight_variable([1, 1, 4096, 4096], name="W7")
            b7 = utils.bias_variable([4096], name="b7")
            conv7 = utils.conv2d_basic(relu_dropout6, W7, b7)
            relu7 = tf.nn.relu(conv7, name="relu7")
            if self.debug:
                utils.add_activation_summary(relu7)
            relu_dropout7 = tf.nn.dropout(relu7, keep_prob=keep_prob)

            W8 = utils.weight_variable([1, 1, 4096, self.n_classes], name="W8")
            b8 = utils.bias_variable([self.n_classes], name="b8")
            conv8 = utils.conv2d_basic(relu_dropout7, W8, b8)
            # annotation_pred1 = tf.argmax(conv8, dimension=3, name="prediction1")

            deconv_shape1 = self.image_net["pool4"].get_shape()
            W_t1 = utils.weight_variable([4, 4, deconv_shape1[3].value, self.n_classes], name="W_t1")
            b_t1 = utils.bias_variable([deconv_shape1[3].value], name="b_t1")
            conv_t1 = utils.conv2d_transpose_strided(conv8, W_t1, b_t1, output_shape=tf.shape(self.image_net["pool4"]))
            fuse_1 = tf.add(conv_t1, self.image_net["pool4"], name="fuse_1")

            deconv_shape2 = self.image_net["pool3"].get_shape()
            W_t2 = utils.weight_variable([4, 4, deconv_shape2[3].value, deconv_shape1[3].value], name="W_t2")
            b_t2 = utils.bias_variable([deconv_shape2[3].value], name="b_t2")
            conv_t2 = utils.conv2d_transpose_strided(fuse_1, W_t2, b_t2, output_shape=tf.shape(self.image_net["pool3"]))
            fuse_2 = tf.add(conv_t2, self.image_net["pool3"], name="fuse_2")

            shape = tf.shape(image)
            #deconv_shape3 = tf.stack([shape[0], shape[1], shape[2], self.n_classes])
            deconv_shape3 = tf.stack([shape[0], shape[1], shape[2], 3 * (self.n_classes - 1)])
            W_t3 = utils.weight_variable([16, 16, 3 * (self.n_classes - 1), deconv_shape2[3].value], name="W_t3")
            b_t3 = utils.bias_variable([3 * (self.n_classes - 1)], name="b_t3")
            conv_t3 = utils.conv2d_transpose_strided(fuse_2, W_t3, b_t3, output_shape=deconv_shape3, stride=8)
            #tanh_t3 = tf.math.sigmoid(conv_t3)
            for i in range(0, 3 * (self.n_classes - 1), 3):
                current = tf.math.sigmoid(conv_t3[:, :, :, i:i+2])
                if i == 0:
                    tanh_t3 = current
                else:
                    tanh_t3 = tf.concat([tanh_t3, current], axis=-1)
                tanh_t3 = tf.concat([tanh_t3, tf.nn.relu(conv_t3[:, :, :, i+2:i+3])], axis=-1)

        return tanh_t3

    def build_centers_optimizer(self, loss_val, var_list):
        with tf.variable_scope("centers"):
            centers_optimizer = tf.train.AdamOptimizer(self.centers_learning_rate)
            '''
            centers_grads, centers_variables = zip(*centers_optimizer.compute_gradients(loss_val, var_list=var_list))
            if self.debug:
                # print(len(var_list))
                for grad, var in centers_grads:
                    utils.add_gradient_summary(grad, var)
            centers_grads, _ = tf.clip_by_global_norm(centers_grads, 5.0)
            
            return centers_optimizer.apply_gradients(zip(centers_grads, centers_variables))
            '''
            centers_grads = centers_optimizer.compute_gradients(loss_val, var_list=var_list)
            return centers_optimizer.apply_gradients(centers_grads)

    def build_pose_branch(self):
        self.pose_keep_probability = tf.placeholder(tf.float32, name="pose_keep_probabilty")
        self.pose_annotation = tf.placeholder(tf.float32, shape=[None, 4 * (self.n_classes - 1)], name="pose_annotation")
        self.coordinates = tf.placeholder(tf.float32, shape=[self.n_points, 1, 3], name="pose_coordinates")
        self.rois = tf.placeholder(tf.float32, shape=[None, None, 4])

        self.pose_pred = self.build_pose_layers(self.image, self.pose_keep_probability, self.rois)
        pose_loss = SLoss(q_true=self.pose_annotation, q_pred=self.pose_pred, M=self.coordinates, n_classes=self.n_classes - 1, no_of_points=self.n_points)
        pose_loss_summary = tf.summary.scalar("pose_entropy", pose_loss)
        pose_trainable_var = tf.trainable_variables(scope="pose")
        if self.debug:
            for var in labels_trainable_var:
                utils.add_to_regularization_and_summary(var)
        self.pose_train_op = self.build_pose_optimizer(pose_loss, pose_trainable_var)
        self.pose_pred_accuracy = SLoss_accuracy(q_true=self.pose_annotation, q_pred=self.pose_pred, n_classes=self.n_classes - 1)

        print("Setting up pose summary op...")
        pose_summary_op = tf.summary.merge_all()
    
    def build_pose_layers(self, image, keep_prob, rois):
        TRUNCATE = 0
        with tf.variable_scope("pose"):
            
            shape6 = tf.shape(self.image_net["conv5_3"])
            deconv_shape6 = tf.stack([shape6[0], 56, 56, 512])
            W_6 = utils.weight_variable([4, 4, 512, 512], name="W_6")
            b_6 = utils.bias_variable([512], name="b_6")
            conv_6 = utils.conv2d_transpose_strided(self.image_net["conv5_3"], W_6, b_6, output_shape=deconv_shape6, stride=4)

            roi_layer6 = ROIPoolingLayer(self.roi_pool_h, self.roi_pool_w)
            pooled_features6 = roi_layer6([conv_6, rois])
            pooled_features6 = tf.nn.dropout(pooled_features6, keep_prob=keep_prob)
            
            shape7 = tf.shape(self.image_net["conv4_3"])
            deconv_shape7 = tf.stack([shape7[0], 56, 56, 512])
            W_7 = utils.weight_variable([2, 2, 512, 512], name="W_7")
            b_7 = utils.bias_variable([512], name="b_7")
            conv_7 = utils.conv2d_transpose_strided(self.image_net["conv4_3"], W_7, b_7, output_shape=deconv_shape7, stride=2)

            roi_layer7 = ROIPoolingLayer(self.roi_pool_h, self.roi_pool_w)
            pooled_features7 = roi_layer7([conv_7, rois])
            pooled_features7 = tf.nn.dropout(pooled_features7, keep_prob=keep_prob)

            roi_add8 = tf.keras.layers.Add()([pooled_features6, pooled_features7])
            roi_add9 = tf.reduce_sum(roi_add8, axis=1)
            shape = roi_add9.get_shape().as_list()
            dim = 1
            for d in shape[1:]:
                dim *= d
            roi_add9 = tf.reshape(roi_add9, [-1, dim])

            fc9_w = tf.reshape(self.vgg_fc["fc6"][0], [dim, 4096])
            fc9 = tf.nn.bias_add(tf.matmul(roi_add9, fc9_w), self.vgg_fc["fc6"][1])
            fc_dropout9 = tf.nn.dropout(fc9, keep_prob=keep_prob)

            fc10_w = tf.reshape(self.vgg_fc["fc7"][0], [4096, 4096])
            fc10 = tf.nn.bias_add(tf.matmul(fc_dropout9, fc10_w), self.vgg_fc["fc7"][1])
            fc_dropout10 = tf.nn.dropout(fc10, keep_prob=keep_prob)

            W11 = utils.weight_variable([4096, 4 * (self.n_classes - 1)], name="W11")
            b11 = utils.bias_variable([4 * (self.n_classes - 1)], name="b11")
            fc11 = tf.nn.bias_add(tf.matmul(fc_dropout10, W11), b11)
            tanh11 = tf.math.tanh(fc11)
        
        return tanh11

    def build_pose_optimizer(self, loss_val, var_list):
        with tf.variable_scope("pose"):
            pose_optimizer = tf.train.AdamOptimizer(self.pose_learning_rate)
            '''
            pose_grads = pose_optimizer.compute_gradients(loss_val, var_list=var_list)
            if self.debug:
                # print(len(var_list))
                for grad, var in pose_grads:
                    utils.add_gradient_summary(grad, var)
            '''
            pose_grads, pose_variables = zip(*pose_optimizer.compute_gradients(loss_val, var_list=var_list))
            pose_grads, _ = tf.clip_by_global_norm(pose_grads, 2.5)
            
            return pose_optimizer.apply_gradients(zip(pose_grads, pose_variables))
            #return pose_optimizer.apply_gradients(pose_grads)

    def vgg_net(self, weights, image):
        layers = (
            'conv1_1', 'relu1_1', 'conv1_2', 'relu1_2', 'pool1',
            'conv2_1', 'relu2_1', 'conv2_2', 'relu2_2', 'pool2',

            'conv3_1', 'relu3_1', 'conv3_2', 'relu3_2', 'conv3_3',
            'relu3_3', 'conv3_4', 'relu3_4', 'pool3',

            'conv4_1', 'relu4_1', 'conv4_2', 'relu4_2', 'conv4_3',
            'relu4_3', 'conv4_4', 'relu4_4', 'pool4',

            'conv5_1', 'relu5_1', 'conv5_2', 'relu5_2', 'conv5_3',
            'relu5_3', 'conv5_4', 'relu5_4'
        )
        net = {}
        current = image
        for i, name in enumerate(layers):
            kind = name[:4]
            if kind == 'conv':
                kernels, bias = weights[i][0][0][0][0]
                # matconvnet: weights are [width, height, in_channels, out_channels]
                # tensorflow: weights are [height, width, in_channels, out_channels]
                kernels = utils.get_variable(np.transpose(kernels, (1, 0, 2, 3)), name=name + "_w")
                bias = utils.get_variable(bias.reshape(-1), name=name + "_b")
                current = utils.conv2d_basic(current, kernels, bias)
            elif kind == 'relu':
                current = tf.nn.relu(current, name=name)
                if self.debug:
                    utils.add_activation_summary(current)
            elif kind == 'pool':
                current = utils.avg_pool_2x2(current)
            net[name] = current

        return net    

    def vgg_net_fc(self, weights):
        # matconvnet: weights are [width, height, in_channels, out_channels]
        # tensorflow: weights are [height, width, in_channels, out_channels]
        fc_net = {}
        kernels_fc6, bias_fc6 = weights[37][0][0][0][0]
        kernels_fc6 = utils.get_variable(np.transpose(kernels_fc6, (1, 0, 2, 3)), name="fc6_w")
        bias_fc6 = utils.get_variable(bias_fc6.reshape(-1), name="fc6_b")
        fc_net["fc6"] = (kernels_fc6, bias_fc6)

        kernels_fc7, bias_fc7 = weights[39][0][0][0][0]
        kernels_fc7 = utils.get_variable(np.transpose(kernels_fc7, (1, 0, 2, 3)), name="fc7_w")
        bias_fc7 = utils.get_variable(bias_fc7.reshape(-1), name="fc7_b")
        fc_net["fc7"] = (kernels_fc7, bias_fc7)

        return fc_net

    def attach_saver(self, mode):
        self.use_tf_saver = True
        #save_vars = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope=mode)
        save_vars = []
        for branch in mode:
            save_vars += tf.trainable_variables(scope=branch)
        self.saver_tf = tf.train.Saver(save_vars, max_to_keep=1)
