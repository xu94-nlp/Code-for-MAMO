from utils import *


class FeatureMem:
    def __init__(self, n_k, u_emb_dim, base_model, device):
        self.n_k = n_k
        self.base_model = base_model
        self.p_memory = torch.randn(n_k, u_emb_dim, device=device).normal_()  # on device
        u_param, _, _ = base_model.get_weights()
        self.u_memory = []
        for i in range(n_k):
            bias_list = []
            for param in u_param:
                bias_list.append(param.normal_(std=0.05))
            self.u_memory.append(bias_list)
        self.att_values = torch.zeros(n_k).to(device)
        self.device = device

    def read_head(self, p_u, alpha, train=True):
        # get personalized mu
        att_model = Attention(self.n_k).to(self.device)
        """
        p_u is the raw feature.
        """
        attention_values = att_model(p_u, self.p_memory).to(self.device)  # pu on devic
        personalized_mu = get_mu(attention_values, self.u_memory, self.base_model, self.device)
        # update mp
        transposed_att = attention_values.reshape(self.n_k, 1)
        product = torch.mm(transposed_att, p_u)
        if train:
            self.p_memory = alpha * product + (1-alpha) * self.p_memory
        self.att_values = attention_values
        return personalized_mu, attention_values

    def write_head(self, u_grads, lr):
        update_mu(self.att_values, self.u_memory, u_grads, lr)


class TaskMem:
    def __init__(self, n_k, emb_dim, device):
        self.n_k = n_k
        self.memory_UI = torch.rand(n_k, emb_dim *2, emb_dim*2, device=device).normal_()
        self.att_values = torch.zeros(n_k)

    def read_head(self, att_values):
        self.att_values = att_values
        return get_mui(att_values, self.memory_UI, self.n_k)

    def write_head(self, u_mui, lr):
        update_values = update_mui(self.att_values, self.n_k, u_mui)
        self.memory_UI = lr* update_values + (1-lr) * self.memory_UI


def cosine_similarity(input1, input2):
    query_norm = torch.sqrt(torch.sum(input1**2+0.00001, 1))
    doc_norm = torch.sqrt(torch.sum(input2**2+0.00001, 1))

    prod = torch.sum(torch.mul(input1, input2), 1)
    norm_prod = torch.mul(query_norm, doc_norm)

    cos_sim_raw = torch.div(prod, norm_prod)
    return cos_sim_raw


class Attention(torch.nn.Module):
    def __init__(self, n_k, activation='relu'):
        super(Attention, self).__init__()
        self.n_k = n_k
        self.fc_layer = torch.nn.Linear(self.n_k, self.n_k, activation_func(activation))
        self.soft_max_layer = torch.nn.Softmax()

    def forward(self, pu, mp):
        # note that len(mp) = n_k
        # pu from [batch_size, embed_dim] -> [batch_size, embed_dim * n_k] 
        # -> [n_k , batch_size * embed_dim] // confirmed, batch_size = 1.
        # mp: [n_k, u_embed_dim]
        expanded_pu = pu.repeat(1, len(mp)).view(len(mp), -1)  # shape, n_k, pu_dim
        # print("Forward expanded_pu",  expanded_pu.shape)
        # print("MP", mp.shape)
        # print("PU", pu.shape)
        inputs = cosine_similarity(expanded_pu, mp)
        # print("inputs shape", inputs.shape)
        fc_layers = self.fc_layer(inputs)
        attention_values = self.soft_max_layer(fc_layers)
        return attention_values


def get_mu(att_values, mu, model, device):
    mu0,_,_ = model.get_zero_weights()
    # len(mu) = n_k, the # of rate levels.
    attention_values = att_values.reshape(len(mu),1)
    for i in range(len(mu)):
        for j in range(len(mu[i])):
            mu0[j] += attention_values[i] * mu[i][j].to(device)
    return mu0


def update_mu(att_values, mu, grads, lr):
    att_values = att_values.reshape(len(mu), 1)
    for i in range(len(mu)):
        for j in range(len(mu[i])):
            mu[i][j] = lr * att_values[i] * grads[j] + (1-lr) * mu[i][j]


def get_mui(att_values, mui, n_k):
    attention_values = att_values.reshape(n_k, 1, 1)
    attend_mui = torch.mul(attention_values, mui)
    u_mui = attend_mui.sum(dim=0)
    return u_mui


def update_mui(att_values, n_k, u_mui):
    # print("update_mui", u_mui.shape)
    repeat_u_mui = u_mui.unsqueeze(0).repeat(n_k, 1, 1) # add external axis at 0.
    # print("repeat_u_mui.unsqueeze(0)", u_mui.unsqueeze(0).shape)
    # print("repeat_u_mui", repeat_u_mui.shape)
    # print("att_values", att_values.shape)
    attention_tensor = att_values.reshape(n_k, 1, 1)
    # print("reshape att_values", attention_tensor.shape)
    attend_u_mui = torch.mul(attention_tensor, repeat_u_mui)
    return attend_u_mui
