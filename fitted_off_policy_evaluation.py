"""
Created on December 12, 2018

@author: clvoloshin, 
"""
from fitted_algo import FittedAlgo
import numpy as np
from tqdm import tqdm
from env_nn import *

class LakeFittedQEvaluation(FittedAlgo):
    def __init__(self, initial_states, num_inputs, grid_shape, dim_of_actions, max_epochs, gamma,model_type='mlp', position_of_goals=None, position_of_holes=None, num_frame_stack=None):

        '''
        An implementation of fitted Q iteration

        num_inputs: number of inputs
        dim_of_actions: dimension of action space
        max_epochs: positive int, specifies how many iterations to run the algorithm
        gamma: discount factor
        '''
        self.model_type = model_type
        self.initial_states = initial_states
        self.num_inputs = num_inputs
        self.dim_of_actions = dim_of_actions
        self.max_epochs = max_epochs
        self.gamma = gamma
        self.grid_shape = grid_shape
        self.position_of_holes = position_of_holes
        self.position_of_goals = position_of_goals
        self.num_frame_stack = num_frame_stack

        super(LakeFittedQEvaluation, self).__init__()

    def run(self, policy, which_cost, dataset, epochs=500, epsilon=1e-8, desc='FQE', g_idx=None, **kw):
        # dataset is the original dataset generated by pi_{old} to which we will find
        # an approximately optimal Q

        self.Q_k = self.init_Q(model_type=self.model_type, position_of_holes=self.position_of_holes, position_of_goals=self.position_of_goals, num_frame_stack=self.num_frame_stack, **kw)

        X_a = np.hstack(dataset.get_state_action_pairs())
        x_prime = dataset['x_prime']

        index_of_skim = self.skim(X_a, x_prime)
        X_a = X_a[index_of_skim]
        x_prime = x_prime[index_of_skim][:,0]
        dataset.set_cost(which_cost, idx=g_idx)
        dataset_costs = dataset['cost'][index_of_skim]
        dones = dataset['done'][index_of_skim]

        for k in tqdm(range(self.max_epochs), desc=desc):

            # {((x,a), r+gamma* Q(x',pi(x')))}
            
            # if k == 0:
            #     # Q_0 = 0 everywhere
            #     costs = dataset_costs
            # else:
            costs = dataset_costs + (self.gamma*self.Q_k(x_prime, policy(x_prime)).reshape(-1)*(1-dones.astype(int))).reshape(-1)

            self.fit(X_a, costs, epochs=epochs, batch_size=X_a.shape[0], epsilon=epsilon, evaluate=False, verbose=0)

            # if not self.Q_k.callbacks_list[0].converged:
            #     print 'Continuing training due to lack of convergence'
            #     self.fit(X_a, costs, epochs=epochs, batch_size=X_a.shape[0], epsilon=epsilon, evaluate=False, verbose=0)


        return np.mean([self.Q_k(state, policy(state)) for state in self.initial_states])

    def init_Q(self, epsilon=1e-10, **kw):
        return LakeNN(self.num_inputs, 1, self.grid_shape, self.dim_of_actions, self.gamma, epsilon, **kw)

class CarFittedQEvaluation(FittedAlgo):
    def __init__(self, state_space_dim, dim_of_actions, max_epochs, gamma, model_type='cnn', num_frame_stack=None):

        '''
        An implementation of fitted Q iteration

        num_inputs: number of inputs
        dim_of_actions: dimension of action space
        max_epochs: positive int, specifies how many iterations to run the algorithm
        gamma: discount factor
        '''
        self.model_type = model_type


        self.state_space_dim = state_space_dim
        self.dim_of_actions = dim_of_actions
        self.max_epochs = max_epochs
        self.gamma = gamma
        self.num_frame_stack = num_frame_stack

        super(CarFittedQEvaluation, self).__init__()

    def run(self, policy, which_cost, dataset, epochs=1, epsilon=1e-8, desc='FQE', g_idx=None, **kw):
        # dataset is the original dataset generated by pi_{old} to which we will find
        # an approximately optimal Q
        
        dataset.set_cost(which_cost, idx=g_idx)
        
        self.Q_k = self.init_Q(model_type=self.model_type, num_frame_stack=self.num_frame_stack, **kw)
        self.Q_k_minus_1 = self.init_Q(model_type=self.model_type, num_frame_stack=self.num_frame_stack, **kw)
        self.Q_k.copy_over_to(self.Q_k_minus_1)
        
        # setting up graph. Why do i need to do this?!
        # self.Q_k_minus_1(dataset['x'][0][np.newaxis,...], [0])
        # self.Q_k(dataset['x'][0][np.newaxis,...], [0])

        for k in tqdm(range(self.max_epochs), desc=desc):
            
            batch_size = 128
            steps_per_epoch = np.ceil(int(len(dataset)/float(batch_size)))
            gen = self.data_generator(dataset, policy, batch_size=batch_size)
            self.fit_generator(gen, epochs=epochs, steps_per_epoch=steps_per_epoch, epsilon=epsilon, evaluate=False, verbose=0)
            self.Q_k.copy_over_to(self.Q_k_minus_1)

        try:
            initial_states = np.unique([episode.frames[[0]*episode.num_frame_stack] for episode in dataset.episodes], axis=0)
        except:
            initial_states = dataset['x'][[0]*dataset.num_frame_stack]
        
        initial_states = self.Q_k.representation(initial_states)
        actions = policy(initial_states, x_preprocessed = True)
        Q_val = self.Q_k.all_actions(initial_states, x_preprocessed=True)[np.arange(len(actions)), actions]
        return np.mean(Q_val)

    def data_generator(self, dataset, policy, batch_size = 64):
    
        dataset_length = len(dataset)
        random_permutation = np.random.permutation(np.arange(dataset_length))
        for i in range(int(np.ceil(len(dataset)/float(batch_size)))):
            batch_idxs = random_permutation[(i*batch_size):((i+1)*batch_size)]
              
            X_a = [x[batch_idxs] for x in dataset.get_state_action_pairs()]
            x_prime = dataset['x_prime'][batch_idxs]
            dataset_costs = dataset['cost'][batch_idxs]
            dones = dataset['done'][batch_idxs]

            x_prime = self.Q_k_minus_1.representation(x_prime)

            actions = policy(x_prime, x_preprocessed = True)
            Q_val = self.Q_k_minus_1.all_actions(x_prime, x_preprocessed=True)[np.arange(len(actions)), actions]
            costs = dataset_costs + (self.gamma*Q_val.reshape(-1)*(1-dones.astype(int))).reshape(-1)

            X = self.Q_k_minus_1.representation(X_a[0], X_a[1])

            yield (X, costs)

    def init_Q(self, epsilon=1e-10, **kw):
        return CarNN(self.state_space_dim, self.dim_of_actions, self.gamma, convergence_of_model_epsilon=epsilon, **kw)

