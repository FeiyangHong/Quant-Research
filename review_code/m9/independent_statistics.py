"""Independent bootstrap-t/HAC kernel, copied from the M8 independent review.

No production evaluation imports. New utility arithmetic is kept separate from
raw return arithmetic and no utility quantity is converted into currency.
"""
import numpy as np
def hac(values,lag):
    values=np.atleast_2d(values)
    length=values.shape[1]
    centered=values-values.mean(axis=1)[:,None]
    long_variance=np.einsum("ij,ij->i",centered,centered)/length
    for distance in range(1,lag+1):
        covariance=np.einsum("ij,ij->i",centered[:,distance:],centered[:,:-distance])/length
        long_variance+=2*(1-distance/(lag+1))*covariance
    return np.sqrt(np.maximum(0,long_variance)/length)


def intervals(values,block):
    values=np.asarray(values,dtype=float)
    count=len(values)
    lag=max(1,int(4*(count/100)**(2/9)))
    se=hac(values,lag)[0]
    rng=np.random.Generator(np.random.PCG64(20261114))
    starts=rng.integers(0,count,size=(5000,(count+block-1)//block))
    centered=values-values.mean()
    studentized=[]
    for start in range(0,5000,100):
        indices=(starts[start:start+100,:,None]+np.arange(block))%count
        draw=centered[indices.reshape(len(indices),-1)[:,:count]]
        standard_error=hac(draw,lag)
        assert np.all(standard_error>1e-15)
        studentized.extend(draw.mean(axis=1)/standard_error)
    low,high=np.quantile(studentized,[.025,.975])
    return dict(hac_lag=lag,hac_se=float(se),ci95=[float(values.mean()-high*se),float(values.mean()-low*se)])


def concentration(contributions):
    positive=sorted(((key,value) for key,value in contributions.items() if value>0),key=lambda kv:(-kv[1],kv[0]))
    total_positive=sum(value for key,value in positive)
    magnitude=sum(abs(value) for value in contributions.values())
    top=sorted(contributions.items(),key=lambda kv:(-abs(kv[1]),kv[0]))
    return dict(total_signed=float(sum(contributions.values())),total_positive=float(total_positive),total_absolute=float(magnitude),
        largest_absolute=[dict(key=key,value=float(value)) for key,value in top[:5]],
        largest_positive_share=float(positive[0][1]/total_positive) if total_positive else None,
        top3_positive_share=float(sum(value for key,value in positive[:3])/total_positive) if total_positive else None)
