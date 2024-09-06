# AUTOGENERATED! DO NOT EDIT! File to edit: src/uId3.ipynb (unless otherwise specified).

__all__ = ['UId3']

# Cell
from sklearn.base import BaseEstimator
import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier

from .attribute import Attribute
from .data import Data
from .entropy_evaluator import EntropyEvaluator, UncertainEntropyEvaluator
from .tree import Tree
from .tree_node import TreeNode
from .tree_edge import TreeEdge
from .tree_evaluator import TreeEvaluator
from .value import Value
from .utils import StandardRescaler
from multiprocessing import cpu_count,Pool
import shap
from sklearn.svm import LinearSVC
from sklearn.preprocessing import StandardScaler

# Cell
class UId3(BaseEstimator):
    
    PARALLEL_ENTRY_FACTOR = 1000

    def __init__(self, max_depth=None, node_size_limit = 1, grow_confidence_threshold = 0, min_impurity_decrease=0):
        """A decision tree classifier with customizable parameters for controlling tree growth.

        Parameters:
        -----------
        :param max_depth: int or None, default=None
            The maximum depth of the tree. If None, then nodes are expanded until all leaves are pure or until all leaves
            contain less than `node_size_limit` samples.
        :param node_size_limit: int, default=1
            The minimum number of samples required to split a node further. If the number of samples at a node is less than
            `node_size_limit`, the node is not split, and it becomes a leaf.
        :param grow_confidence_threshold: float, default=0
            The minimum confidence level required for a split to occur. Splits with a confidence level below this threshold
            are not performed. Confidence level is typically defined by impurity measures such as Gini impurity or entropy.
        :param min_impurity_decrease: float, default=0
            The minimum decrease in impurity required for a split to occur. A split is only considered if it leads to at least
            this amount of impurity decrease. If a split does not meet this criterion, it is not performed.

        Attributes:
        -----------
        TREE_DEPTH_LIMIT: int or None
            The maximum depth of the tree.
        NODE_SIZE_LIMIT: int
            The minimum number of samples required to split a node further.
        GROW_CONFIDENCE_THRESHOLD: float
            The minimum confidence level required for a split to occur.
        tree: object or None
            The decision tree model constructed after fitting the data.
        node_size_limit: int
            The minimum number of samples required to split a node further.
        min_impurity_decrease: float
            The minimum decrease in impurity required for a split to occur.
        """
        self.TREE_DEPTH_LIMIT= max_depth
        self.NODE_SIZE_LIMIT = node_size_limit
        self.GROW_CONFIDENCE_THRESHOLD = grow_confidence_threshold
        self.tree = None
        self.node_size_limit = node_size_limit
        self.min_impurity_decrease=min_impurity_decrease
        
    def fit(self, data, y=None, *, depth,  entropyEvaluator, classifier=None, beta=1, discount_importance = False, prune=False, oblique=False,  n_jobs=None): 
        """Fits pyUID3 tree, optionally using SHAP values calculated for the classifier.

        Parameters
        ----------
        data : pyuid3.Data
            Data object containing dataset. It has to be object from pyuid3.Data
        y : np.array
            Vector containing target values
        depth : int, optional
            This parameter should not be used. It is used internally by recurrent calls to govern the depth of the tree.
        entropyEvaluator: pyuid3.EntropyEvaluator
            Object responisble for calculating split criterion. Default is UncertainEntropyEvaluator. Although the naming might be confusing, other possibilities are:
            UncertainGiniEvaluator, UncertainSqrtGiniEvaluator
        classifier: optional
            A classifier that is designed according to sckit paradigm. It is required from the classifier to have predict_proba function. Default is None
        beta: int
            Parameter being a weight in harmonic mean between score obtained from EntropyEvaluator and SHAP values. 
            The greater the value the more important are SHAP values when selecting a split. Default is 1.
        discount_importance: boolean,
            Parameter indicating if the SHAP importances should be calculated resively at every split, or if the importances calculated for the whole data should be used.
            In the latter case, the importances are discounted by the percentage of reduction in split criterion (e.g. Information Gain). Default it False.
        prune: boolean, optional
            Define if after training the tree should be pruned. The prounning is done by looking at the change in prediction on a training set. If removing a branch does not change the prediction outcome, the branch is pruned. It will provide more general trees, i.e.rules extracted from branches will have more coverage, but their precission may drop.
        oblique: boolean, optional
            Define if the tree should assume building linear slipts, instead of simple inequality-based spolits. Deafult False.
        n_jobs: int, optional
            Number of processess to use when building a tree. Default is None
        

        Returns
        -------
        pyuid3.Tree
            a fitted decision tree
        """

        if classifier is not None and len(data.get_instances()) >= self.NODE_SIZE_LIMIT:
            datadf = data.to_dataframe()
            try:
                explainer = shap.Explainer(classifier,datadf.iloc[:,:-1])
                if hasattr(explainer, "shap_values"):
                    shap_values = explainer.shap_values(datadf.iloc[:,:-1],check_additivity=False)
                else:
                    shap_values = explainer(datadf.iloc[:,:-1]).values
                    shap_values=[sv for sv in np.moveaxis(shap_values, 2,0)]
                if hasattr(explainer, "expected_value"):
                    expected_values = explainer.expected_value
                else:
                    expected_values=[np.mean(v) for v in shap_values]
            except TypeError:
                explainer = shap.Explainer(classifier.predict_proba, datadf.iloc[:,:-1])
                shap_values = explainer(datadf.iloc[:,:-1]).values
                shap_values=[sv for sv in np.moveaxis(shap_values, 2,0)]
                expected_values=[np.mean(v) for v in shap_values]
            
            
            if type(shap_values) is not list:
                shap_values = [-shap_values, shap_values]
                expected_values=[np.mean(v) for v in shap_values]


            #find max and rescale:
            maxshap = max([np.max(np.abs(sv)) for sv in shap_values]) #ADD
            shap_values = [sv/maxshap for sv in shap_values] #ADD
            
            shap_dict={}
            expected_dict={}
            for i,v in enumerate(shap_values):
                shap_dict[str(i)] = pd.DataFrame(v, columns = datadf.columns[:-1])
                expected_dict[str(i)] = expected_values[i] #/maxshap #ADD
            data = data.set_importances(pd.concat(shap_dict,axis=1).fillna(0), expected_values = expected_dict)
        
        if len(data.get_instances()) < self.NODE_SIZE_LIMIT:
            return None
        if self.TREE_DEPTH_LIMIT is not None and depth > self.TREE_DEPTH_LIMIT:
            return None
        entropy = entropyEvaluator.calculate_entropy(data)

        data.update_attribute_domains()

        # of the set is heterogeneous or no attributes to split, just class -- return
        # leaf
        if entropy == 0 or len(data.get_attributes()) == 1:
            # create the only node and summary for it
            class_att = data.get_class_attribute()
            root = TreeNode(class_att.get_name(), data.calculate_statistics(class_att))
            root.set_type(class_att.get_type())
            tree = Tree(root)
            if depth == 0:
                self.tree = tree
            return tree

        info_gain = 0
        best_split = None
        
        cl=[]
        for i in data.get_instances():
            cl.append(i.get_reading_for_attribute(data.get_class_attribute()).get_most_probable().get_name())

        n_jobs_inner = 1
        if n_jobs is not None:
            if n_jobs == -1:
                n_jobs=n_jobs_inner = cpu_count()
            if len(data)/n_jobs_inner < UId3.PARALLEL_ENTRY_FACTOR:
                n_jobs_inner = max(1,int(len(data)/UId3.PARALLEL_ENTRY_FACTOR)) 
            if n_jobs > len(data.get_attributes()):
                n_jobs = len(data.get_attributes())-1
            if (len(data)*len(data.get_attributes()))/n_jobs < UId3.PARALLEL_ENTRY_FACTOR:
                n_jobs = max(1,int((len(data)*len(data.get_attributes()))/UId3.PARALLEL_ENTRY_FACTOR))
        else:
            n_jobs = 1
            
        gains = []
        if n_jobs > 1 and n_jobs_inner < len(data.get_attributes()):
            with Pool(n_jobs) as pool:
                results = pool.starmap(UId3.try_attribute_for_split, [(data, a, cl, entropy,  entropyEvaluator,self.min_impurity_decrease, beta, 1,classifier is not None) for a in data.get_attributes() if a != data.get_class_attribute()])
                temp_gain = 0
                for temp_gain, pure_temp_gain, best_split_candidate in results:
                    if best_split_candidate is not None:
                        gains.append((temp_gain,pure_temp_gain,best_split_candidate))
                    if temp_gain > info_gain and (pure_temp_gain/entropy)>=self.min_impurity_decrease:
                        info_gain = temp_gain
                        pure_info_gain=pure_temp_gain
                        best_split = best_split_candidate
        else:
            for a in data.get_attributes():
                if data.get_class_attribute() == a:
                    continue
                temp_gain, pure_temp_gain, best_split_candidate=self.try_attribute_for_split(data, a, cl, entropy,  entropyEvaluator,self.min_impurity_decrease, beta=beta, n_jobs=n_jobs, shap = classifier is not None)
                if best_split_candidate is not None:
                    gains.append((temp_gain,pure_temp_gain,best_split_candidate))
                if temp_gain > info_gain and (pure_temp_gain/entropy)>=self.min_impurity_decrease:
                    info_gain = temp_gain
                    pure_info_gain=pure_temp_gain
                    best_split = best_split_candidate

        ###########################################
        #if there is a shap
        if oblique:
            svm_temp_gain = pure_svm_temp_gain = 0
            if classifier is not None:
                #select two most important features according to SHAP
                ivmean = data.to_dataframe_importances(average_absolute=True)
                idd = np.flip(np.argsort(ivmean)[-2:])
                features = [f for f in data.get_attributes() if f not in [data.get_class_attribute().get_name()]]
                svc_features = [features[i] for i in idd]
                svm_temp_gain, pure_svm_temp_gain, svm_best_splitting_att,svm_best_linear_att, boundary_expression = UId3.get_oblique_gains(data, svc_features,entropyEvaluator, entropy, beta, shap=True)
   
            elif len(gains) > 1:
                #take two most importnat selected by Dtree
                gains = sorted(gains,key=lambda x: x[0],reverse=True)
                svc_features = [gains[0][2].get_name(),gains[1][2].get_name()]
                svm_temp_gain, pure_svm_temp_gain, svm_best_splitting_att, svm_best_linear_att, boundary_expression = UId3.get_oblique_gains(data, svc_features,entropyEvaluator, entropy, beta, shap=False)
        
            if svm_temp_gain > info_gain and (pure_svm_temp_gain/entropy)>=self.min_impurity_decrease:
                info_gain = svm_temp_gain
                pure_info_gain=pure_svm_temp_gain
                best_split = svm_best_splitting_att
                best_split.set_value_to_split_on(boundary_expression)

        ###########################################
        
        # if nothing better can happen
        if best_split == None:
            # create the only node and summary for it
            class_att = data.get_class_attribute()
            root = TreeNode(class_att.get_name(), data.calculate_statistics(class_att))
            root.set_type(class_att.get_type())
            tree = Tree(root)
            if depth == 0:
                self.tree = tree
            return tree

        # Create root node, and recursively go deeper into the tree.
        class_att = data.get_class_attribute()
        class_stats = data.calculate_statistics(class_att)
        root = TreeNode(best_split.get_name(), class_stats)
        root.set_type(class_att.get_type())
        
        classes = []
        # attach newly created trees
        for val in best_split.get_splittable_domain():
            if best_split.get_type() == Attribute.TYPE_NOMINAL:
                best_split_stats = data.calculate_statistics(best_split)
                new_data = data.filter_nominal_attribute_value(best_split, val)
                if not discount_importance:
                    subtree = self.fit(new_data, classifier=classifier, entropyEvaluator=entropyEvaluator, depth=depth + 1, beta=beta, prune=prune, oblique=oblique,n_jobs=n_jobs)
                else:
                    if oblique and svm_temp_gain > 0:
                        new_data = new_data.reduce_importance_for_attribute(best_split, best_split.get_importance_gain()/entropy/2.0)
                        new_data = new_data.reduce_importance_for_attribute(svm_best_linear_att, best_split.get_importance_gain()/entropy/2.0)
                    else:
                        new_data = new_data.reduce_importance_for_attribute(best_split, best_split.get_importance_gain()/entropy)
                    
                    subtree = self.fit(new_data, discount_importance=True, classifier=None, entropyEvaluator=entropyEvaluator, depth=depth + 1,beta=beta, prune=prune,oblique=oblique, n_jobs=n_jobs)
                
                if subtree and best_split_stats.get_most_probable().get_confidence() > self.GROW_CONFIDENCE_THRESHOLD:
                    if subtree.get_root().is_leaf():
                        classes.append(subtree.get_root().get_stats().get_most_probable().get_name())
                    root.add_edge(TreeEdge(Value(val, best_split_stats.get_avg_confidence()), subtree.get_root()))
                    root.set_infogain(best_split.get_importance_gain())

            elif best_split.get_type() == Attribute.TYPE_NUMERICAL:
                best_split_stats = data.calculate_statistics(best_split)
                new_data_less_then,new_data_greater_equal = data.filter_numeric_attribute_value_expr(best_split, val)
                
                
                if len(new_data_less_then) >= self.node_size_limit and len(new_data_greater_equal) >= self.node_size_limit:
                    if not discount_importance:
                        subtree_less_than = self.fit(new_data_less_then, classifier=classifier, entropyEvaluator=entropyEvaluator, depth=depth + 1, beta=beta, prune=prune, oblique=oblique,n_jobs=n_jobs)
                        subtree_greater_equal = self.fit(new_data_greater_equal, classifier=classifier, entropyEvaluator=entropyEvaluator, depth=depth + 1, beta=beta, prune=prune,oblique=oblique, n_jobs=n_jobs)
                    else:
                        if oblique and svm_temp_gain > 0:
                            new_data_less_then = new_data_less_then.reduce_importance_for_attribute(best_split, best_split.get_importance_gain()/entropy/2.0)
                            new_data_greater_equal = new_data_greater_equal.reduce_importance_for_attribute(best_split, best_split.get_importance_gain()/entropy/2.0)
                            
                            new_data_less_then = new_data_less_then.reduce_importance_for_attribute(svm_best_linear_att, best_split.get_importance_gain()/entropy/2.0)
                            new_data_greater_equal = new_data_greater_equal.reduce_importance_for_attribute(svm_best_linear_att, best_split.get_importance_gain()/entropy/2.0)
                        else:
                            new_data_less_then = new_data_less_then.reduce_importance_for_attribute(best_split, best_split.get_importance_gain()/entropy)
                            new_data_greater_equal = new_data_greater_equal.reduce_importance_for_attribute(best_split, best_split.get_importance_gain()/entropy)
                        
                        
                        subtree_less_than = self.fit(new_data_less_then, classifier=None,  entropyEvaluator=entropyEvaluator, depth=depth + 1, discount_importance=True,beta=beta, prune=prune,oblique=oblique, n_jobs=n_jobs)
                        subtree_greater_equal = self.fit(new_data_greater_equal, classifier=None, entropyEvaluator=entropyEvaluator, depth=depth + 1, discount_importance=True,beta=beta, prune=prune, oblique=oblique,n_jobs=n_jobs)
                        
                    if subtree_less_than and best_split_stats.get_most_probable().get_confidence() > self.GROW_CONFIDENCE_THRESHOLD:
                        root.add_edge(TreeEdge(Value("<" + val, best_split_stats.get_avg_confidence()), subtree_less_than.get_root()))
                        if subtree_less_than.get_root().is_leaf():
                            classes.append(subtree_less_than.get_root().get_stats().get_most_probable().get_name())
                    if subtree_greater_equal and best_split_stats.get_most_probable().get_confidence() > self.GROW_CONFIDENCE_THRESHOLD:
                        root.add_edge(TreeEdge(Value(">=" + val, best_split_stats.get_avg_confidence()), subtree_greater_equal.get_root()))
                        if subtree_greater_equal.get_root().is_leaf():
                            classes.append(subtree_greater_equal.get_root().get_stats().get_most_probable().get_name())
                    root.set_type(Attribute.TYPE_NUMERICAL)
                    root.set_infogain(best_split.get_importance_gain())

        #If all of the leaves predict same class, simply remove them, when prune is True
        if prune and len(classes) == len(root.get_edges()) and len(set(classes)) < 2:
            root.set_edges([])
        
        if len(root.get_edges()) == 0:
            root.set_att(data.get_class_attribute().get_name())
            root.set_type(data.get_class_attribute().get_type())

        self.tree = Tree(root)
        return self.tree

    @staticmethod
    def get_oblique_gains(data, svc_features,entropyEvaluator, globalEntropy, beta, shap):
        svc = LinearSVC()
        datadf = data.to_dataframe()
        if datadf[data.get_class_attribute().get_name()].nunique() < 2:
            return 0, 0, None, None, None
        
        sc = StandardScaler()
        sc.fit(datadf[svc_features])
        datadf.loc[:,svc_features] = sc.transform(datadf.loc[:,svc_features])
        svc.fit(datadf[svc_features], datadf[data.get_class_attribute().get_name()])     

    
        sr = StandardRescaler(sc.mean_, sc.scale_) 
        single_temp_gain_max = 0
        pure_single_temp_gain_max = 0
        pure_single_temp_gain = 0
        boundary_expression=None
        boundary_expression_max=None
        single_temp_gain=0
        splitting_att=None
        linear_relation_att=None
        for ci in range(0,len(svc.coef_)):
            coefs = svc.coef_[ci]
            intercept= svc.intercept_[ci]
            coefs, intercept = sr.rescale(coefs, intercept)
            #transform to canonical form

            sign =  np.sign(coefs[0])
            intercept /= coefs[0] 
            coefs /= coefs[0] 

            #moving to the other side of equation
            coefs[1:] = -1.0*coefs[1:]
            intercept *= -1
            
            if np.isnan(sum(coefs)+intercept):
                continue
            
            boundary_expression = '+'.join([f'{c} * {f}' for c,f in  zip(coefs[1:], svc_features[1:])])+f'+{intercept}'
            splitting_att = data.get_attribute_of_name(svc_features[0])
            linear_relation_att = data.get_attribute_of_name(svc_features[1])
            if sign < 0:
                subdata_less_than,subdata_greater_equal = data.filter_numeric_attribute_value_expr(splitting_att, boundary_expression)
            else:
                subdata_greater_equal,subdata_less_than = data.filter_numeric_attribute_value_expr(splitting_att, boundary_expression)
            #test split entropy

            # in fact, its numeric value test
            stat_for_lt_value = len(subdata_less_than)/len(data)
            stat_for_gte_value = len(subdata_greater_equal)/len(data)

            stats=data.calculate_statistics(splitting_att)
            stats_linear=data.calculate_statistics(linear_relation_att)

            conf_for_value = (stats.get_avg_confidence()+stats_linear.get_avg_confidence())/2
            avg_abs_importance = (stats.get_avg_abs_importance()+stats_linear.get_avg_abs_importance())/2

            single_temp_gain, pure_single_temp_gain=UId3.calculate_gains_numeric(stat_for_lt_value, stat_for_gte_value, conf_for_value,avg_abs_importance,  
                                                                                 subdata_less_than,subdata_greater_equal, splitting_att, entropyEvaluator, globalEntropy, beta, shap)
            if single_temp_gain > single_temp_gain_max:
                single_temp_gain_max=single_temp_gain
                pure_single_temp_gain_max=pure_single_temp_gain
                boundary_expression_max = boundary_expression
        
        
        return single_temp_gain, pure_single_temp_gain, splitting_att, linear_relation_att, boundary_expression_max

        
    
    @staticmethod
    def try_attribute_for_split(data, attribute, cl, globalEntropy, entropyEvaluator,min_impurity_decrease, beta=1, n_jobs=None, shap=False):
        values = attribute.get_domain()
        pure_info_gain = 0
        info_gain=0
        best_split=None
        
        stats = data.calculate_statistics(attribute)
        
        ## start searching for best border values  -- such that class value remains the same for the ranges between them
        if attribute.get_type() == Attribute.TYPE_NUMERICAL:
            if isinstance(entropyEvaluator,UncertainEntropyEvaluator):
                clf_h = DecisionTreeClassifier()
                tmp_df = data.to_dataframe()
                clf_h.fit(tmp_df[attribute.get_name()].values.reshape(-1, 1), tmp_df[data.get_class_attribute().get_name()])
                values = np.array([clf_h.tree_.threshold[0].astype(str)])
            else:
                border_search_list = []
                for i in data.get_instances():
                    v=i.get_reading_for_attribute(attribute).get_most_probable().get_name()
                    border_search_list.append([v])
                border_search_df = pd.DataFrame(border_search_list,columns=['values'])
                border_search_df['values']=border_search_df['values'].astype('f8')
                border_search_df['class'] = cl
                border_search_df=border_search_df.sort_values(by='values')
                border_search_df['values_shift']=border_search_df['values'].shift(1)
                border_search_df['class_shitf'] = border_search_df['class'].shift(1)
                border_search_shift = border_search_df[border_search_df['class_shitf'] != border_search_df['class']]
                values = np.unique((border_search_shift['values']+border_search_shift['values_shift']).dropna()/2).astype('str') # take the middle value
        else:
            values=list(values)

        if n_jobs is not None and attribute.get_type()==Attribute.TYPE_NUMERICAL: 
            if n_jobs == -1:
                n_jobs = cpu_count()
            if len(values)/n_jobs < UId3.PARALLEL_ENTRY_FACTOR:
                n_jobs = max(1,int(len(values)/UId3.PARALLEL_ENTRY_FACTOR))
        else:
            n_jobs = 1

        #divide into j_jobs batches
        if n_jobs > 1:
            values_batches = np.array_split(values, n_jobs)
            with Pool(n_jobs) as pool:
                results = pool.starmap(UId3.calculate_split_criterion, [(v, data, attribute, stats, globalEntropy, entropyEvaluator, min_impurity_decrease,beta,shap) for v in values_batches])
                temp_gain = 0
                for best_split_candidate_c, value_to_split_on_c, temp_gain_c, pure_temp_gain_c in results:
                    if temp_gain_c > temp_gain:
                        best_split_candidate=best_split_candidate_c 
                        value_to_split_on =value_to_split_on_c
                        temp_gain =temp_gain_c
                        pure_temp_gain=pure_temp_gain_c
        else:
            best_split_candidate, value_to_split_on, temp_gain, pure_temp_gain = UId3.calculate_split_criterion(values=values, 
                                                                                                                data=data, 
                                                                                                                attribute=attribute, 
                                                                                                                stats=stats, 
                                                                                                                globalEntropy=globalEntropy, 
                                                                                                                entropyEvaluator=entropyEvaluator, 
                                                                                                                min_impurity_decrease=min_impurity_decrease,
                                                                                                                beta=beta,shap=shap)


        if temp_gain > info_gain and (pure_temp_gain/globalEntropy)>=min_impurity_decrease:
            info_gain = temp_gain
            pure_info_gain=pure_temp_gain
            best_split = best_split_candidate
            best_split_candidate.set_importance_gain(pure_info_gain)
            best_split_candidate.set_value_to_split_on(value_to_split_on)
            
        return info_gain, pure_info_gain, best_split
    
    
    @staticmethod
    def calculate_gains_numeric(stat_for_lt_value, stat_for_gte_value, conf_for_value, avg_abs_importance,  subdata_less_than,subdata_greater_equal, attribute, entropyEvaluator, globalEntropy, beta,shap):
        if shap:
            pure_single_temp_gain = (globalEntropy - (stat_for_lt_value*entropyEvaluator.calculate_entropy(subdata_less_than)+
                                                                           (stat_for_gte_value)*entropyEvaluator.calculate_entropy(subdata_greater_equal) ))


            pure_single_temp_gain_shap = avg_abs_importance*globalEntropy #ADD

            if pure_single_temp_gain*pure_single_temp_gain_shap == 0:
                #to prevent from 0-division
                single_temp_gain=0
            else:
                single_temp_gain =(beta*pure_single_temp_gain_shap*pure_single_temp_gain)/(1+beta)
        else:
            pure_single_temp_gain = (globalEntropy - (stat_for_lt_value*entropyEvaluator.calculate_entropy(subdata_less_than)+
                                                                                   (stat_for_gte_value)*entropyEvaluator.calculate_entropy(subdata_greater_equal) ))
            single_temp_gain = pure_single_temp_gain*conf_for_value
    
        return single_temp_gain, pure_single_temp_gain
    


    @staticmethod
    def calculate_split_criterion( values, data, attribute, stats, globalEntropy, entropyEvaluator,min_impurity_decrease, beta=1, shap=False):
        temp_gain = 0
        temp_shapgain = 0
        temp_numeric_gain = 0
        pure_temp_gain=0
        local_info_gain = 0
        value_to_split_on = None
        best_split = None
        
        for v in values:  
            subdata = None
            subdataLessThan = None
            subdataGreaterEqual = None
                
            if attribute.get_type() == Attribute.TYPE_NOMINAL:
                subdata = data.filter_nominal_attribute_value(attribute, v)
                stat_for_value = len(subdata)/len(data)
                temp_gain += (stat_for_value) * entropyEvaluator.calculate_entropy(subdata)
            elif attribute.get_type() == Attribute.TYPE_NUMERICAL:
                subdata_less_than,subdata_greater_equal = data.filter_numeric_attribute_value(attribute, v)
                stat_for_lt_value = len(subdata_less_than)/len(data)
                stat_for_gte_value = len(subdata_greater_equal)/len(data)
                conf_for_value = stats.get_avg_confidence()
                avg_abs_importance = stats.get_avg_abs_importance()
                single_temp_gain, pure_single_temp_gain=UId3.calculate_gains_numeric(stat_for_lt_value, stat_for_gte_value, conf_for_value,  avg_abs_importance,
                                                                                     subdata_less_than,subdata_greater_equal, 
                                                                                     attribute, entropyEvaluator, globalEntropy, beta, shap)
                    
                    
                if single_temp_gain > temp_numeric_gain:
                    temp_numeric_gain = single_temp_gain
                    temp_gain = single_temp_gain
                    pure_temp_gain= pure_single_temp_gain
                    value_to_split_on = v
                    
        if attribute.get_type() == Attribute.TYPE_NOMINAL:
            conf_for_value = stats.get_avg_confidence()
            pure_temp_gain=globalEntropy-temp_gain
            if shap:
                avg_abs_importance = stats.get_avg_abs_importance()
                pure_temp_gain_shap = avg_abs_importance * globalEntropy
                temp_gain = (pure_temp_gain_shap + beta * pure_temp_gain) / (1 + beta)#((1+beta**2)*pure_temp_gain_shap*pure_temp_gain)/((beta**2*pure_temp_gain_shap)+pure_temp_gain)*conf_for_value
            else:
                temp_gain = conf_for_value*pure_temp_gain

        if temp_gain > local_info_gain and (pure_temp_gain/globalEntropy)>=min_impurity_decrease:
            best_split = attribute
            local_info_gain=temp_gain
 
        return best_split, value_to_split_on, temp_gain, pure_temp_gain

    @staticmethod
    def fit_uncertain_nominal() -> None:
        data = Data.parse_uarff("../resources/machine.nominal.uncertain.arff")
        test = Data.parse_uarff("../resources/machine.nominal.uncertain.arff")

        t = UId3.fit(data, UncertainEntropyEvaluator(), 0)
        br = TreeEvaluator.train_and_test(t, test)

        print("###############################################################")
        print(f"Correctly classified instances: {br.get_accuracy() * 100}%")
        print(f"Incorrectly classified instances: {(1-br.get_accuracy()) * 100}%")
        print("TP Rate", "FP Rate", "Precision", "Recall", "F-Measure", "ROC Area", "Class")

        for class_label in data.get_class_attribute().get_domain():
            cs = br.get_stats_for_label(class_label)
            print(cs.get_TP_rate(), cs.get_FP_rate(), cs.get_precision(), cs.get_recall(), cs.get_F_measure(),
                                cs.get_ROC_area(br), cs.get_class_label())

    def predict(self, X):   # should take array-like X -> predict(X)
        if not isinstance(X, (list, np.ndarray)):
            X = [X]
        predictions = []
        for instance in X:
            att_stats = self.tree.predict(instance)
            predictions.append(att_stats.get_most_probable())
        return predictions