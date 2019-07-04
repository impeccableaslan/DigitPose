import random
import tensorflow as tf
import numpy as np
import cv2

colors = [ [0, 0, 0], [0, 128, 0], [0, 0, 128], [0, 128, 128], [128, 0, 0],
           [128, 0, 128], [128, 128, 0], [128, 128, 128], [0, 0, 64],
           [0, 0, 192], [0, 128, 64], [0, 128, 192], [128, 0, 64], [128, 0, 192] ]

class Batch:
    def __init__(self, im_paths, im_labels, im_orientations, im_coordinates, n_classes, n_points, IMAGE_HW=224):
        self.im_paths = im_paths
        self.im_labels = im_labels
        self.im_orientations = im_orientations
        self.im_coordinates = im_coordinates
        self.n_classes = n_classes
        self.n_points = n_points
        self.IMAGE_HW = IMAGE_HW

    def get_image_and_label(self):
        sample = random.randint(0, len(self.im_paths) - 1)
        img, label = self.load_and_preprocess_image(self.im_paths[sample], self.im_labels[sample])
        return [img], [label]
    
    def get_image_and_label_upToCenters(self):
        sample = random.randint(0, len(self.im_paths) - 1)
        img, label, stack_centerxyz = self.load_and_preprocess_image_upToCenters(self.im_paths[sample], self.im_labels[sample])
        return [img], [label], [stack_centerxyz]

    def get_image_and_label_ALL(self):
        sample = random.randint(0, len(self.im_paths) - 1)
        img, label, stack_centerxyz = self.load_and_preprocess_image_upToCenters(self.im_paths[sample], self.im_labels[sample])
        orientation = self.preprocess_orientations(self.im_orientations[sample])
        coordinates = self.preprocess_coordinates(self.im_coordinates[sample])
        return [img], [label], [stack_centerxyz], [orientation], [coordinates]

    def preprocess_image(self, image):
        image = cv2.imread(image)
        #image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        image = cv2.merge((image, image, image))
        image = cv2.resize(image, (self.IMAGE_HW, self.IMAGE_HW))
        #image = image / 255.0
        image = np.asarray(image)
        return image

    def preprocess_label(self, label_path):
        label = cv2.imread(label_path)
        stack = []
        for c in colors:
            mask = cv2.inRange(label, np.array(c), np.array(c)) / 255
            mask = cv2.resize(mask, (self.IMAGE_HW, self.IMAGE_HW))
            stack.append(mask)
        stack = np.asarray(stack)
        stack = np.moveaxis(stack, 0, -1)
        return stack
    
    def preprocess_orientations(self, orientation_path):
        with open(orientation_path, "r") as file:
            oriens = file.readlines()
        allqs = []
        for c in range(self.n_classes - 1):
            if len(oriens) > c:
                qs = oriens[c].split(',')
                qs = [float(q) for q in qs]
                allqs += qs
            else:
                allqs += [0, 0, 0, 1]
        allqs = np.asarray(allqs)
        return allqs
    
    def preprocess_coordinates(self, coordinates_path):
        with open(coordinates_path, "r") as file:
            coords = file.readlines()
        allcoords = []
        for _ in range(self.n_points):
            sample = random.randint(0, len(coords) - 1)
            cs = coords[sample].split(',')
            cs = [float(c) for c in cs]
            allcoords.append(cs)
        allcoords = np.asarray(allcoords)
        return allcoords

    def preprocess_label_upToCenters(self, label_path):
        stack = []
        voidClass = np.full([self.IMAGE_HW, self.IMAGE_HW], 1)
        stack_centerx, stack_centery, stack_centerz = [], [], []
        with open(label_path, "r") as file:
            gts = file.readlines()
        for _ in range(self.n_classes - 1):
            label = np.zeros([self.IMAGE_HW, self.IMAGE_HW])
            directionx = np.zeros([self.IMAGE_HW, self.IMAGE_HW])
            directiony = np.zeros([self.IMAGE_HW, self.IMAGE_HW])
            directionz = np.zeros([self.IMAGE_HW, self.IMAGE_HW])
            for line in gts:
                pts = line.split(',')
                i = int(pts[0])
                j = self.IMAGE_HW - 1 - int(pts[1])
                voidClass[i][j] = 0
                label[i][j] = 1
                directionx[i][j] = float(pts[2])
                directiony[i][j] = -float(pts[3])
                directionz[i][j] = float(pts[4])
            stack.append(label)
            stack_centerx.append(directionx)
            stack_centery.append(directiony)
            stack_centerz.append(directionz)
        stack.append(voidClass)
        stack = np.asarray(stack)
        stack = np.moveaxis(stack, 0, -1)
        stack_centerxyz = stack_centerx + stack_centery + stack_centerz
        stack_centerxyz = np.asarray(stack_centerxyz)
        stack_centerxyz = np.moveaxis(stack_centerxyz, 0, -1)
        return stack, stack_centerxyz

    def load_and_preprocess_image(self, path, label):
        return self.preprocess_image(path), self.preprocess_label(label)
    
    def load_and_preprocess_image_upToCenters(self, path, label):
        img = self.preprocess_image(path)
        stack, stack_centerxyz = self.preprocess_label_upToCenters(label)
        return img, stack, stack_centerxyz
