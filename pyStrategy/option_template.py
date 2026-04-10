# encoding: UTF-8
"""
期权常见函数，波动率计算
更新时间： 2023-07-13 15:33:56
"""

import numpy as np
import scipy.optimize as opt
import scipy.stats as sps

import ctaEngine  # type: ignore


class Option(object):
    """
    期权常见函数方法, 

    Args:
        option_type: 看涨期权[Call、C、call]；看跌期权 [Put、P、put]
        underlying_price: 标的当前价格
        k: 执行价
        t: 距离到期日剩余时间，以年计算
        r: 无风险利率
        market_price: 期权当前市场价格
        sigma: 波动率，填 0 表示使用 BSM 计算的 IV 进行计算
        dividend_rate: 股息率
    """

    def __init__(
        self, 
        option_type: str, 
        underlying_price: float, 
        k: float, 
        t: float,
        r: float,
        market_price: float, 
        dividend_rate: float,
        sigma: float = 0
    ) -> None:
        self.option_type = 'Call' if option_type in ['c', 'C', 'Call', 'call'] else 'Put'
        self.option_type_sign = 1.0 if self.option_type == 'Call' else -1.0
        self.underlying_price = underlying_price * 1.0

        self.k = k * 1.0
        self.t = t * 1.0
        self.r = r * 1.0
        self.dividend_rate = dividend_rate * 1.0
        self.market_price = market_price * 1.0
        self.sigma = sigma * 1.0 if sigma else self.bs_iv()

        self.star = 0.0
        self.q = 0.0

    def bs_iv(self):
        """二分法计算隐含波动率"""
        sigma_top = 2  # 波动率上限
        sigma_floor = 0.01  # 波动率下限
        count = 0  # 计数器
        min_precision = 0.00001  # 精度
        s_t = self.underlying_price * np.exp(-self.dividend_rate * self.t)
        k_t = self.k * np.exp(-self.r * self.t)

        if self.option_type_sign * (s_t - k_t) >= self.market_price:
            return 0.8

        o_sigma_top = self.change_option(sigma=sigma_top)
        o_sigma_floor = self.change_option(sigma=sigma_floor)

        while (
            (abs(o_sigma_floor.bs_price() - self.market_price) >= min_precision) and
            (abs(o_sigma_top.bs_price() - self.market_price) >= min_precision)
        ):
            sigma = (sigma_floor + sigma_top) / 2

            o_mid = self.change_option(sigma=sigma)

            if abs(o_mid.bs_price() - self.market_price) <= min_precision:
                return sigma
            elif ((o_sigma_floor.bs_price() - self.market_price) *
                  (o_mid.bs_price() - self.market_price) < 0):
                sigma_top = sigma
            else:
                sigma_floor = sigma

            count += 1

            if count > 200:
                return 0

    def change_option(self, sigma) -> "Option":
        """使用迭代法时会使用"""
        option_template = Option(
            option_type=self.option_type,
            underlying_price=self.underlying_price,
            k=self.k,
            t=self.t,
            r=self.r,
            sigma=sigma,
            market_price=self.market_price,
            dividend_rate=self.dividend_rate
        )

        return option_template

    def bs_iv_newton(self) -> float:
        """牛顿迭代法计算隐含波动率"""
        max_count = 200
        min_precision = 0.01
        sigma = 0.5

        s_t = self.underlying_price * np.exp(-self.dividend_rate * self.t)
        k_t = self.k * np.exp(-self.r * self.t)

        if self.option_type_sign * (s_t - k_t) >= self.market_price:
            return 0.8

        for _ in range(max_count):
            o_mid = self.change_option(sigma=sigma)

            price = o_mid.bs_price()
            vega = o_mid.bs_vega()
            diff = self.market_price - price

            if abs(diff) < min_precision:
                return sigma

            sigma = sigma + diff / vega

        return sigma

    def bs_iv_func(self, sigma: float) -> float:
        """已知波动率，计算市场价格和该波动率下的 BS 公式价格"""
        op = self.change_option(sigma=sigma)
        value_price = op.bs_price()

        return abs(self.market_price - value_price)

    def bs_iv_optimize(self):
        """单纯形算法计算隐含波动率"""
        try:
            iv = opt.minimize(self.bs_iv_func, np.array(self.sigma), method='nelder-mead')
            return iv.x[0]
        except:
            ctaEngine.writeLog("超出边界")

    def bs_iv_root(self):
        """通过非线性方程求根来计算隐含波动率"""
        try:
            iv = opt.root(self.bs_iv_func, np.array(self.sigma))
            return iv.x[0]
        except:
            ctaEngine.writeLog("超出边界")

    def baw_iv(self):
        """二分法计算美式期权隐含波动率"""
        sigma_top = 2  # 波动率上限
        sigma_floor = 0.01  # 波动率下限
        count = 0  # 计数器
        min_precision = 0.00001  # 精度
        s_t = self.underlying_price * np.exp(-self.dividend_rate * self.t)
        k_t = self.k * np.exp(-self.r * self.t)

        if self.option_type_sign * (s_t - k_t) >= self.market_price:
            return 0.8

        o_sigma_top = self.change_option(sigma=sigma_top)
        o_sigma_floor = self.change_option(sigma=sigma_floor)

        while (abs(sigma_top - sigma_floor) > min_precision or
            (
                abs(o_sigma_floor.baw_price() - self.market_price) >= min_precision and
                min_precision <= abs(o_sigma_top.baw_price() - self.market_price) >= min_precision
            )
        ):
            sigma = (sigma_floor + sigma_top) / 2
            o_mid = self.change_option(sigma=sigma)

            if abs(o_mid.baw_price() - self.market_price) <= min_precision:
                return sigma
            elif (o_sigma_floor.baw_price() - self.market_price) * (o_mid.baw_price() - self.market_price) < 0:
                sigma_top = sigma
            else:
                sigma_floor = sigma

            count += 1

            if count > 200:
                return 0

    def d_1(self):
        return self.d_1_pre(self.underlying_price)

    def d_1_pre(self, underlying_price):
        ln_p = np.log(underlying_price / self.k)
        d_1_pre = (ln_p + (self.r - self.dividend_rate + .5 * self.sigma ** 2) * self.t) / self.sigma_t()
        return d_1_pre

    def d_2(self):
        return self.d_1() - self.sigma_t()

    def d_1_1(self):
        return (1 / np.sqrt(2 * np.pi)) * np.exp((-self.d_1() ** 2) / 2)

    def d_2_1(self):
        return (1 / np.sqrt(2 * np.pi)) * np.exp((-self.d_2() ** 2) / 2)

    def n_d_1(self):
        return self.option_type_sign * sps.norm.cdf(self.option_type_sign * self.d_1())

    def n_d_2(self):
        return self.option_type_sign * sps.norm.cdf(self.option_type_sign * self.d_2())

    def s_t(self):
        return self.underlying_price * np.exp(-self.dividend_rate * self.t)

    def sigma_t(self):
        return self.sigma * np.sqrt(self.t)

    def bs_price(self):
        return (self.s_t() * self.n_d_1() - self.k * np.exp(-self.r * self.t) * self.n_d_2())

    def bs_price_pre(self, underlying_price):
        """可填标的价格的 BSM 计算期权价格法"""
        s_t = underlying_price * np.exp(-self.dividend_rate * self.t)
        n_d_1 = self.option_type_sign * sps.norm.cdf(self.option_type_sign * self.d_1_pre(underlying_price))

        d_2 = self.d_1_pre(underlying_price) - self.sigma_t()
        n_d_2 = self.option_type_sign * sps.norm.cdf(self.option_type_sign * d_2)
        value_price = (s_t * n_d_1 - self.k * np.exp(-self.r * self.t) * n_d_2)

        return value_price

    def bs_delta(self):
        return (self.n_d_1()) * np.exp(-self.dividend_rate * self.t)

    def bs_gamma(self):
        return np.exp(-self.dividend_rate * self.t) * self.d_1_1() / (self.underlying_price * self.sigma_t())

    def bs_vega(self):
        vega = self.s_t() * np.sqrt(self.t) * self.d_1_1()

        return vega / 100

    def bs_theta(self):
        """折合为每天的时间损耗率"""
        year_theta = (
            (-self.s_t() * self.d_1_1() * self.sigma) / (2 * np.sqrt(self.t)) -
            self.r * self.n_d_2() * self.k * np.exp(-self.r * self.t) +
            self.dividend_rate * self.n_d_1() * self.s_t()
        )

        return year_theta / 365

    def bs_rho(self):
        rho = (self.k * self.t * np.exp(-self.r * self.t) * self.n_d_2())
        return rho / 100

    def bs_rho_q(self):
        rho_q = (self.s_t() * self.t * self.n_d_1())
        return rho_q / 100

    def bs_vanna(self):
        return -np.exp(-self.dividend_rate * self.t) * self.d_1_1() * self.d_2() / self.sigma

    def crr_m(self):
        """无息标的的二叉树美式期权定价模型"""
        N = 5000
        dt = self.t / N
        u = np.exp(self.sigma * np.sqrt(dt))
        d = 1.0 / u
        a = np.exp(self.r * dt)
        p = (a - d) / (u - d)
        q = 1.0 - p
        s_t = np.array([(self.underlying_price * u ** j * d ** (N - j)) for j in range(N + 1)])

        value = np.maximum(self.option_type_sign * (s_t - self.k), 0)

        for _ in range(N - 1, -1, -1):
            value[:-1] = np.exp(-self.r * dt) * (p * value[1:] + q * value[:-1])
            s_t = s_t * u

            value = np.maximum(self.option_type_sign * (s_t - self.k), value)

        return value

    def crr_price(self):
        """定价价格"""
        return self.crr_m()[0]

    def crr_delta(self):
        """delta"""
        delta = (
            (self.crr_m()[2] - self.crr_m()[1]) /
            (self.underlying_price * (
                np.exp(self.sigma * np.sqrt(self.t / 5000)) -
                1 / np.exp(self.sigma * np.sqrt(self.t / 5000))
            ))
        )
        return delta

    def crr_gamma(self):
        """gamma"""

        temp1 = (
            np.exp(self.sigma * np.sqrt(self.t / 5000)) ** 2 -
            (1 / np.exp(self.sigma * np.sqrt(self.t / 5000))) ** 2
        )

        temp2 = (
            self.underlying_price * np.exp(self.sigma * np.sqrt(self.t / 5000)) ** 2 -
            self.underlying_price
        )

        temp3 = (
            self.underlying_price - 
            self.underlying_price * (1 / np.exp(self.sigma * np.sqrt(self.t / 5000))) ** 2
        )

        h = 0.5 * self.underlying_price * temp1

        change = (
            abs((self.crr_m()[5] - self.crr_m()[4]) / temp2) -
            abs((self.crr_m()[4] - self.crr_m()[3]) / temp3)
        )

        gamma = self.option_type_sign * change / h 

        return gamma

    def crr_vega(self):
        """vega"""
        f = self.crr_price()
        self.sigma += 0.01

        f_change = self.crr_price()
        vega = (f_change - f) * 100

        self.sigma -= 0.01

        return vega / 100

    def crr_theta(self):
        """theta"""
        f = self.crr_price()
        self.t -= 1 / 365

        f_change = self.crr_price()
        theta = (f_change - f)
        self.t += 1 / 365

        return theta

    def crr_rho(self):
        """rho"""
        f = self.crr_price()
        self.r += 0.01

        f_change = self.crr_price()
        rho = (f_change - f) * 100
        self.r -= 0.01

        return rho / 100

    def baw_func(self, underlying_price):
        """定价模型方程"""
        start_n_d_1 = sps.norm.cdf(self.option_type_sign * self.d_1_pre(underlying_price))

        value_1 = self.bs_price_pre(underlying_price) + self.american_option_premium(underlying_price)
        value_2 = (1 - np.exp(- self.dividend_rate * self.t) * start_n_d_1) * self.option_type_sign

        option_init = (underlying_price - self.k) * self.option_type_sign

        return (value_1 + value_2 * underlying_price / self.q - option_init) ** 2

    def baw_simulate(self):
        """定价模型方程求解"""
        self.q = self.q_1_2()
        data = opt.fmin(self.baw_func, self.underlying_price)
        self.star = data[0]
        return

    def american_option_premium(self, star):
        """美式期权溢价"""
        american_option_premium = self.A(star) * (self.underlying_price / star)  ** self.q
        return american_option_premium

    def baw_price(self):
        """美式期权定价模型"""
        self.baw_simulate()

        baw_price_pre = self.bs_price() + self.american_option_premium(self.star) 
        check_sign = self.underlying_price * self.option_type_sign < self.star * self.option_type_sign

        return baw_price_pre if check_sign else  self.option_type_sign * (self.underlying_price - self.k)
    
    def A(self, underlying_price):
        """计算美式期权溢价系数 A"""
        start_n_d_1 = sps.norm.cdf(self.option_type_sign * self.d_1_pre(underlying_price))
        temp = 1 - np.exp(- self.dividend_rate * self.t) * start_n_d_1

        return self.option_type_sign * temp * underlying_price / self.q
    
    def q_1_2(self):
        "计算美式期权溢价系数 q1 和 q2"
        parm_m = 2 * self.r / self.sigma ** 2
        parm_n = 2 * (self.r - self.dividend_rate) / self.sigma ** 2
        parm_x = 1 - np.exp(-self.r * self.t)

        temp1 = 4 * parm_m / parm_x if self.r > 0 else 0
        temp2 = parm_n - 1

        return 0.5 * self.option_type_sign * (-temp2 + np.sqrt(temp2 ** 2 + temp1))

    def baw_delta(self):
        """baw 美式期权定价模型 delta"""
        self.baw_simulate()
        
        return self.bs_delta() + self.A(self.star) / self.star 

    def baw_gamma(self):
        """baw 美式期权定价模型 gamma"""
        self.baw_simulate()

        return self.bs_gamma() + self.A(self.star) * (self.q - 1) / (self.underlying_price * self.star * self.q)

    def baw_vega(self):
        """baw 美式期权定价模型 vega"""
        f = self.baw_price()
        self.sigma += 0.01

        f_change = self.baw_price()
        vega = (f_change - f)
        self.sigma -= 0.01

        return vega

    def baw_theta(self):
        """baw 美式期权定价模型 theta, 日度"""
        f = self.baw_price()
        self.t -= 1.0 / 365

        f_change = self.baw_price()
        theta = (f_change - f)
        self.t += 1.0 / 365

        return theta

    def baw_rho(self):
        """baw 美式期权定价模型 rho"""
        f = self.baw_price()
        self.r += 0.01

        f_change = self.baw_price()
        rho = (f_change - f)
        self.r -= 0.01

        return rho

    def back_tree_m(self):
        """美式三叉树定价模型"""
        N = 3500
        dt = self.t / N
        dx = self.sigma * np.sqrt(3 * dt)

        niu = self.r - self.dividend_rate - 0.5 * self.sigma ** 2
        pu = 0.5 * dt * ((self.sigma / dx) ** 2 + niu / dx)
        pm = 1 - dt * (self.sigma / dx) ** 2 - self.r * dt
        pd = 0.5 * dt * ((self.sigma / dx) ** 2 - niu / dx)

        set_array = self.underlying_price * np.exp(dx * np.linspace(-N, N, 2 * N + 1))
        strike_array = self.k * np.ones(len(set_array))

        if self.option_type_sign == 1:
            value = np.maximum(set_array - strike_array, 0)
        else:
            value = np.maximum(strike_array - set_array, 0)

        for i in range(1, N + 1):
            length = len(value)
            option_value = np.zeros(length)

            option_value[i:length - i] = (
                pu * value[i + 1:length - i + 1] +
                pm * value[i:length - i] +
                pd * value[i - 1:length - i - 1]
            )

            if self.option_type_sign == 1.0:
                option_value = np.maximum(option_value, set_array - strike_array)
            else:
                option_value = np.maximum(option_value, strike_array - set_array)

            value = option_value

        return value[N]

    def back_tree(self):
        """标准欧式三叉树定价模型"""
        N = 3500
        dt = self.t / N
        dx = self.sigma * np.sqrt(3 * dt)
        niu = self.r - self.dividend_rate - 0.5 * self.sigma ** 2

        pu = 0.5 * dt * ((self.sigma / dx) ** 2 + niu / dx)
        pm = 1 - dt * (self.sigma / dx) ** 2 - self.r * dt
        pd = 0.5 * dt * ((self.sigma / dx) ** 2 - niu / dx)

        set_array = self.underlying_price * np.exp(dx * np.linspace(-N, N, 2 * N + 1))
        strike_array = self.k * np.ones(len(set_array))

        if self.option_type_sign == 1:
            value = np.maximum(set_array - strike_array, 0)
        else:
            value = np.maximum(strike_array - set_array, 0)

        for i in range(1, N + 1):
            length = len(value)
            option_value = np.zeros(length)

            option_value[i:length - i] = (
                pu * value[i + 1:length - i + 1] +
                pm * value[i:length - i] +
                pd * value[i - 1:length - i - 1]
            )

            value = option_value

        return value[N]
