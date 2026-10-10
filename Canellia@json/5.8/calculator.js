// Bounded arithmetic parser. User input is never executed as JavaScript.
const FUNCTIONS = Object.freeze(Object.fromEntries([
    'abs', 'acos', 'acosh', 'asin', 'asinh', 'atan', 'atanh', 'atan2',
    'ceil', 'cbrt', 'cos', 'cosh', 'exp', 'expm1', 'floor', 'hypot',
    'log', 'log1p', 'log2', 'log10', 'max', 'min', 'pow', 'round',
    'sign', 'sin', 'sinh', 'sqrt', 'tan', 'tanh', 'trunc'
].map(name => [name, Math[name]])));
const CONSTANTS = Object.freeze({PI: Math.PI, E: Math.E, LN2: Math.LN2,
    LN10: Math.LN10, LOG2E: Math.LOG2E, LOG10E: Math.LOG10E,
    SQRT1_2: Math.SQRT1_2, SQRT2: Math.SQRT2});

function calculate(expression) {
    if (typeof expression !== 'string' || expression.length > 512) throw new Error('Expression is too long');
    const tokens = [];
    let offset = 0;
    while (offset < expression.length) {
        if (/\s/.test(expression[offset])) { offset++; continue; }
        const match = /^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|^[A-Za-z][A-Za-z0-9_]*|^\*\*|^[+\-*/%^(),]/.exec(expression.slice(offset));
        if (!match) throw new Error('Unsupported character');
        tokens.push(match[0]); offset += match[0].length;
        if (tokens.length > 256) throw new Error('Expression is too complex');
    }
    let index = 0, depth = 0;
    const finite = value => {
        if (!Number.isFinite(value)) throw new Error('Result is not finite');
        return value;
    };
    function primary() {
        if (++depth > 32) throw new Error('Expression is too deeply nested');
        let value;
        const token = tokens[index++];
        if (token === '+' || token === '-') {
            value = power();
            if (token === '-') value = -value;
        } else if (token === '(') {
            value = sum();
            if (tokens[index++] !== ')') throw new Error('Missing closing parenthesis');
        } else if (token && /^(?:\d|\.)/.test(token)) {
            value = Number(token);
        } else if (Object.prototype.hasOwnProperty.call(CONSTANTS, token)) {
            value = CONSTANTS[token];
        } else if (Object.prototype.hasOwnProperty.call(FUNCTIONS, token)) {
            if (tokens[index++] !== '(') throw new Error('Function requires parentheses');
            const args = [];
            if (tokens[index] !== ')') {
                do {
                    args.push(sum());
                    if (args.length > 16) throw new Error('Too many function arguments');
                } while (tokens[index] === ',' && ++index);
            }
            if (tokens[index++] !== ')') throw new Error('Missing closing parenthesis');
            const arity = ['pow', 'atan2'].includes(token) ? 2 : ['min', 'max', 'hypot'].includes(token) ? null : 1;
            if (args.length === 0 || (arity !== null && args.length !== arity)) throw new Error('Invalid function arguments');
            value = FUNCTIONS[token](...args);
        } else {
            throw new Error('Unknown value or function');
        }
        depth--;
        return finite(value);
    }
    function power() {
        const left = primary();
        if (tokens[index] === '**' || tokens[index] === '^') {
            index++;
            return finite(Math.pow(left, power()));
        }
        return left;
    }
    function product() {
        let result = power();
        while (['*', '/', '%'].includes(tokens[index])) {
            const operation = tokens[index++], right = power();
            result = finite(operation === '*' ? result * right : operation === '/' ? result / right : result % right);
        }
        return result;
    }
    function sum() {
        let result = product();
        while (tokens[index] === '+' || tokens[index] === '-') {
            const operation = tokens[index++], right = product();
            result = finite(operation === '+' ? result + right : result - right);
        }
        return result;
    }
    const result = sum();
    if (index !== tokens.length) throw new Error('Unexpected token');
    return finite(result);
}
module.exports = {calculate};
