# ML engineering

- **Data is the product.** Most ML wins come from better labels, not better architectures. Spend the first weeks understanding the data: distribution, leakage, label quality, train/test contamination. Modeling is dessert.
- **A proper split is non-negotiable.** Train / validation / test, with no leakage between them. Time series? Split by time, not by row. Multi-user? Group by user. The wrong split gives 99% accuracy in dev and a disaster in prod.
- **Baseline first, fancy later.** Logistic regression / gradient boosting beats the deep learning paper on tabular data 80% of the time. Build the simplest thing that could plausibly work; that becomes your honest baseline.
- **Reproducibility is engineering, not optional.** Pin the data version, the random seed, the library versions, the GPU type. If you can't reproduce a metric a week later, the metric is a fairy tale.
- **Evaluate before you optimize.** Define the metric *first*, including its acceptable range. Optimizing without a target leads to "I improved AUC by 1.5%, why isn't the product better?" Aligning the metric with the business outcome is half the work.
- **Bias toward holistic evaluation.** Headline accuracy + calibration + per-subgroup performance + worst-case slice. A model that's 95% overall but 30% on the smallest customer segment is a launch incident, not a launch.
- **Track experiments deliberately.** ML / data version / code version / config / metrics, in one place. Spreadsheet or MLflow or Weights & Biases — pick something and commit. "I tried that last week and it didn't work" is not data.
- **Production != notebook.** Validate inputs at inference time, log predictions and outcomes, gate model rollouts with shadow traffic before live, monitor for drift continuously. The notebook does science; the production stack does *engineering*.
- **Monitor for drift, not just for accuracy.** Input distributions shift before label-derived metrics move. Track feature-by-feature distance from the training set; alert before performance craters.
- **A/B test launches.** A new model that "looks better offline" can lose to the old one in live traffic — selection bias, latency, downstream interactions. Holdout group, statistical significance, run it.
- **Cost is a real metric.** A 50-ms model that's 1% better isn't an upgrade from a 5-ms baseline if the difference doesn't move dollars. Latency, GPU hours, retraining cost all count.
- **Privacy and fairness are not bolt-ons.** Audit feature use against your privacy stance *before* training. Fairness audits per protected class *before* launch. Reverting a deployed model is much harder than vetting it.
- **Document the model.** Inputs, outputs, training data span, intended use, known failure modes. A model card lives next to the code. Future-you will be grateful.
