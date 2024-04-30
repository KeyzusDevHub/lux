__all__ = ['UncertainSMOTE']

from imblearn.over_sampling._smote.base import BaseSMOTE
import numpy as np
import warnings
from scipy import sparse
from sklearn.utils import _safe_indexing, check_array, check_random_state
from sklearn.metrics import pairwise_distances


class UncertainSMOTE(BaseSMOTE):
        
    def __init__(
        self,
        *,
        predict_proba,
        sampling_strategy="all",
        random_state=None,
        k_neighbors=5,
        n_jobs=None,
        sigma=1,
        m_neighbors=10,
        min_samples=0.1,
        instance_to_explain=None, 
        kind="borderline-1",
    ):
        """An implementation of Synthetic Minority Over-sampling Technique (SMOTE) with handling of uncertain samples.
            Parameters:
            -----------
            :param predict_proba: callable
                A function returning probability estimates for samples.
            :type predict_proba: callable
            :param sampling_strategy: float, str, dict, or callable, default='all'
                The sampling strategy to use. Can be a float representing the desired ratio of minority class samples over
                the majority class samples after resampling, or one of {'all', 'not minority', 'minority'}. Alternatively, it
                can be a dictionary where the keys represent the class labels and the values represent the desired number of
                samples for each class, or a callable function returning a dictionary.
            :type sampling_strategy: float, str, dict, or callable
            :param random_state: int, RandomState instance or None, default=None
                Controls the randomness of the algorithm.
            :type random_state: int, RandomState instance or None
            :param k_neighbors: int, default=5
                Number of nearest neighbors to used to construct synthetic samples.
            :type k_neighbors: int
            :param n_jobs: int or None, default=None
                Number of CPU cores used during the computation.
            :type n_jobs: int or None
            :param sigma: float, default=1
                Parameter controlling the thresholding of confidence intervals for identifying uncertain samples.
            :type sigma: float
            :param m_neighbors: int, default=10
                Number of nearest neighbors to consider when estimating if a sample is in danger.
            :type m_neighbors: int
            :param min_samples: float, default=0.1
                Fraction of the maximum class samples to be added as additional synthetic samples.
            :type min_samples: float
            :param instance_to_explain: array-like of shape (n_features,) or None, default=None
                An instance to be used for generating samples around.
            :type instance_to_explain: array-like of shape (n_features,) or None
            :param kind: {'borderline-1', 'borderline-2'}, default='borderline-1'
                The kind of borderline samples to detect. If 'borderline-1', it identifies samples that are
                borderline to a single class. If 'borderline-2', it identifies samples that are borderline to
                multiple classes.
            :type kind: {'borderline-1', 'borderline-2'}

            Attributes:
            -----------
            :sampling_strategy_: dict
                A dictionary containing the actual number of samples for each class after resampling.
        """

        super().__init__(
            sampling_strategy=sampling_strategy,
            random_state=random_state,
            k_neighbors=k_neighbors,
            n_jobs=n_jobs,
        )
        self.m_neighbors = m_neighbors
        self.kind = kind
        self.predict_proba=predict_proba
        self.sigma=sigma
        self.min_samples=min_samples
        self.instance_to_explain = instance_to_explain


    def _fit_resample(self, X, y):
        """

        :param X:
        :param y:
        :return:
        """
        # FIXME: to be removed in 0.12
        if self.n_jobs is not None:
            warnings.warn(
                "The parameter `n_jobs` has been deprecated in 0.10 and will be "
                "removed in 0.12. You can pass an nearest neighbors estimator where "
                "`n_jobs` is already set instead.",
                FutureWarning,
            )

        self._validate_estimator()

        X_resampled = X.copy()
        y_resampled = y.copy()
        
        _, counts = np.unique(y_resampled, return_counts=True)
        samples_max=max(counts)
        additional_samples = int(self.min_samples*samples_max)
            

        #n_samples can be passed as an argument, n_iterations can also be used here
        for class_sample, n_samples in self.sampling_strategy_.items():
            n_samples+=additional_samples

            target_class_indices = np.flatnonzero(y == class_sample)
            X_class = _safe_indexing(X, target_class_indices)

            #self.nn_m_.fit(X)
            danger_index = self._in_danger_noise(
                #self.nn_m_, 
                self.predict_proba,
                X_class, class_sample, y, kind="danger"
            )
            if not any(danger_index):
                continue

            self.nn_k_.fit(X_class)
            nns = self.nn_k_.kneighbors(
                _safe_indexing(X_class, danger_index), return_distance=False
            )[:, 1:]

            # divergence between borderline-1 and borderline-2
            if self.kind == "borderline-1":
                # Create synthetic samples for borderline points.
                X_new, y_new = self._make_samples(
                    _safe_indexing(X_class, danger_index),
                    y.dtype,
                    class_sample,
                    X_class,
                    nns,
                    n_samples,
                )
                if sparse.issparse(X_new):
                    X_resampled = sparse.vstack([X_resampled, X_new])
                else:
                    X_resampled = np.vstack((X_resampled, X_new))
                y_resampled = np.hstack((y_resampled, y_new))

            elif self.kind == "borderline-2":
                random_state = check_random_state(self.random_state)
                fractions = random_state.beta(10, 10)

                # only minority
                X_new_1, y_new_1 = self._make_samples(
                    _safe_indexing(X_class, danger_index),
                    y.dtype,
                    class_sample,
                    X_class,
                    nns,
                    int(fractions * (n_samples + 1)),
                    step_size=1.0,
                )

                # we use a one-vs-rest policy to handle the multiclass in which
                # new samples will be created considering not only the majority
                # class but all over classes.
                X_new_2, y_new_2 = self._make_samples(
                    _safe_indexing(X_class, danger_index),
                    y.dtype,
                    class_sample,
                    _safe_indexing(X, np.flatnonzero(y != class_sample)),
                    nns,
                    int((1 - fractions) * n_samples),
                    step_size=0.5,
                )

                if sparse.issparse(X_resampled):
                    X_resampled = sparse.vstack([X_resampled, X_new_1, X_new_2])
                else:
                    X_resampled = np.vstack((X_resampled, X_new_1, X_new_2))
                y_resampled = np.hstack((y_resampled, y_new_1, y_new_2))

        return X_resampled, y_resampled
    
    
    
    def _in_danger_noise(self, predict_proba, samples, target_class, y, kind="danger"):
        """
        Estimate if a set of sample are in danger or noise.
        :param predict_proba:
           function returning probability estimates for samples
        :param samples: {array-like, sparse matrix} of shape (n_samples, n_features).
           The samples to check if either they are in danger or not.
        :param target_class: nt or str.
           The target corresponding class being over-sampled.
        :param y: array-like of shape (n_samples,).
           The true label in order to check the neighbour labels.
        :param kind: {'danger', 'noise'}, default='danger'
            The type of classification to use. Can be either:
            - If 'danger', check if samples are in danger,
            - If 'noise', check if samples are noise.

        :return: ndarray of shape (n_samples,). A boolean array where True refer to samples in danger or noise.
        """
        
        c_labels  = samples[np.argmax(self.predict_proba(samples),axis=1) ==target_class]
        prediction_certainty = np.max(self.predict_proba(c_labels),axis=1)
        
        #shuld this be thresholded like that, or keep n-lowest?
        confidence_threshold = np.mean(prediction_certainty)-self.sigma*np.std(prediction_certainty) #changed to + (plus)
        
        if self.instance_to_explain is not None:
            distances = pairwise_distances(self.instance_to_explain.reshape(1,-1),c_labels)  
            distancee_threshold = np.mean(distances)-self.sigma*np.std(distances)
            distance_mask = (distances < distancee_threshold)[0]
        else:
            distance_mask = (prediction_certainty<0)

        if kind == "danger":
            return np.bitwise_or(prediction_certainty<confidence_threshold, #changed fom <
                                         distance_mask)
        else:  
            return prediction_certainty<0 #always false
        
        
        
       
        
        
    