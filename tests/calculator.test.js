const {test} = require('node:test');
const assert = require('node:assert/strict');
for (const version of ['4.0', '5.8']) {
    const {calculate} = require('../Canellia@json/' + version + '/calculator');
    test(version + ': arithmetic precedence, functions and constants', () => {
        for (const [expression, expected] of [['2+3*4',14],['(2+3)*4',20],['2**3**2',512],['-2^2',-4],['2^-2',.25],['1e3+.5',1000.5],['sqrt(81)',9],['pow(2,3)+max(1,8,4)',16],['100%7',2]]) {
            assert.equal(calculate(expression), expected, expression);
        }
        assert(Math.abs(calculate('sin(PI/2)') - 1) < 1e-12);
    });
    test(version + ': scripts, invalid and unbounded expressions are rejected', () => {
        for (const expression of ['','while(true){}','global.stage.destroy()','Math.constructor("return this")()','__proto__','1;2','2+','1/0','sqrt(-1)','1e999','random()', '('.repeat(80)+'1'+')'.repeat(80), '1+'.repeat(300)+'1']) {
            assert.throws(() => calculate(expression), expression);
        }
    });
}

for (const version of ['4.0','5.8']) {
    test(version + ': 1000 seeded arithmetic trees agree with their mathematical model', () => {
        const {calculate} = require('../Canellia@json/' + version + '/calculator');
        let seed=874621;
        const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/2**32;};
        function tree(depth) {
            if(!depth || random()<0.3){const value=Math.floor(random()*20)-10;return {expression:'('+value+')',value};}
            const left=tree(depth-1),right=tree(depth-1);
            const op=['+','-','*'][Math.floor(random()*3)];
            return {expression:'('+left.expression+op+right.expression+')',value:op==='+'?left.value+right.value:op==='-'?left.value-right.value:left.value*right.value};
        }
        for(let i=0;i<1000;i++){const model=tree(4);assert.equal(calculate(model.expression),model.value,model.expression);}
    });
}
