import{l as k}from"./pools-Bjy8oDhC.js";import{m as b,d as h,n as x,c as C,b as t,w as a,e as r,r as w,o as z,a as e,t as _,h as m,_ as S}from"./index-DUlOAYYB.js";function T(v,o){return b.get(`/stats/${v}/usage`,{params:o})}const P={class:"stat-icon",style:{background:"#e8f5e9"}},j={class:"stat-info"},B={class:"stat-value"},D={class:"stat-icon",style:{background:"#e3f2fd"}},H={class:"stat-info"},K={class:"stat-value"},$={class:"stat-icon",style:{background:"#fce4ec"}},O={class:"stat-info"},A={class:"stat-value"},N={class:"stat-icon",style:{background:"#fff3e0"}},R={class:"stat-info"},V={class:"stat-value"},X=h({__name:"Dashboard",setup(v){const o=w({total_calls:0,success_calls:0,failed_calls:0,active_keys:0,active_pools:0});async function y(){try{const s=(await k({page:1,page_size:100})).data.items;o.value.active_pools=s.filter(i=>i.is_active).length;let l=0,c=0,n=0,p=0;for(const i of s)try{const d=await T(i.identifier,{seconds:86400}),u=d.data.summary||{};l+=u.total||0,c+=u.success||0,n+=u.failed||0,p+=d.data.by_key?Object.keys(d.data.by_key).length:0}catch{}o.value.total_calls=l,o.value.success_calls=c,o.value.failed_calls=n,o.value.active_keys=p}catch{}}return x(y),(f,s)=>{const l=r("t-icon"),c=r("t-card"),n=r("t-col"),p=r("t-row"),i=r("t-button"),d=r("t-tab-panel"),u=r("t-tabs");return z(),C("div",null,[t(p,{gutter:[16,16]},{default:a(()=>[t(n,{span:3},{default:a(()=>[t(c,{class:"stat-card",bordered:!1},{default:a(()=>[e("div",P,[t(l,{name:"call",size:"24px",style:{color:"#4caf50"}})]),e("div",j,[e("div",B,_(o.value.total_calls),1),s[2]||(s[2]=e("div",{class:"stat-label"},"总调用次数",-1))])]),_:1})]),_:1}),t(n,{span:3},{default:a(()=>[t(c,{class:"stat-card",bordered:!1},{default:a(()=>[e("div",D,[t(l,{name:"check-circle",size:"24px",style:{color:"#2196f3"}})]),e("div",H,[e("div",K,_(o.value.success_calls),1),s[3]||(s[3]=e("div",{class:"stat-label"},"成功调用",-1))])]),_:1})]),_:1}),t(n,{span:3},{default:a(()=>[t(c,{class:"stat-card",bordered:!1},{default:a(()=>[e("div",$,[t(l,{name:"lock-on",size:"24px",style:{color:"#e91e63"}})]),e("div",O,[e("div",A,_(o.value.active_keys),1),s[4]||(s[4]=e("div",{class:"stat-label"},"活跃 Key",-1))])]),_:1})]),_:1}),t(n,{span:3},{default:a(()=>[t(c,{class:"stat-card",bordered:!1},{default:a(()=>[e("div",N,[t(l,{name:"server",size:"24px",style:{color:"#ff9800"}})]),e("div",R,[e("div",V,_(o.value.active_pools),1),s[5]||(s[5]=e("div",{class:"stat-label"},"活跃池",-1))])]),_:1})]),_:1})]),_:1}),t(c,{title:"快速操作",bordered:!1,style:{"margin-top":"16px"}},{default:a(()=>[t(p,{gutter:[16,16]},{default:a(()=>[t(n,{span:4},{default:a(()=>[t(i,{block:"",size:"large",variant:"outline",onClick:s[0]||(s[0]=g=>f.$router.push("/keys"))},{default:a(()=>[t(l,{name:"add",style:{"margin-right":"4px"}}),s[6]||(s[6]=m(" 添加 API Key ",-1))]),_:1})]),_:1}),t(n,{span:4},{default:a(()=>[t(i,{block:"",size:"large",variant:"outline",onClick:s[1]||(s[1]=g=>f.$router.push("/pools"))},{default:a(()=>[t(l,{name:"server",style:{"margin-right":"4px"}}),s[7]||(s[7]=m(" 创建密钥池 ",-1))]),_:1})]),_:1}),t(n,{span:4},{default:a(()=>[t(i,{block:"",size:"large",variant:"outline",onClick:y},{default:a(()=>[t(l,{name:"refresh",style:{"margin-right":"4px"}}),s[8]||(s[8]=m(" 刷新数据 ",-1))]),_:1})]),_:1})]),_:1})]),_:1}),t(c,{title:"SDK 调用示例",bordered:!1,style:{"margin-top":"16px"}},{default:a(()=>[t(u,null,{default:a(()=>[t(d,{value:"python",label:"Python SDK"},{default:a(()=>[...s[9]||(s[9]=[e("div",{class:"code-block"},[e("pre",null,[e("code",null,`from apipool import connect, login

# 方式1: 已有 token
manager = connect("http://localhost:8000", "my-pool", "your-jwt-token")
result = manager.dummyclient.some_method()

# 方式2: 用户名密码登录
tokens = login("http://localhost:8000", "username", "password")
manager = connect("http://localhost:8000", "my-pool", tokens["access_token"])`)])],-1)])]),_:1}),t(d,{value:"curl",label:"cURL"},{default:a(()=>[...s[10]||(s[10]=[e("div",{class:"code-block"},[e("pre",null,[e("code",null,`# 获取 Token
curl -X POST http://localhost:8000/api/v1/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"username":"admin","password":"admin123"}'

# 代理调用 (invoke)
curl -X POST http://localhost:8000/api/v1/proxy/my-pool/invoke \\
  -H "Authorization: Bearer <token>" \\
  -H "Content-Type: application/json" \\
  -d '{"attr_path":["some_method"],"args":[],"kwargs":{}}'

# 代理调用 (call)
curl -X POST http://localhost:8000/api/v1/proxy/my-pool/call \\
  -H "Authorization: Bearer <token>" \\
  -H "Content-Type: application/json" \\
  -d '{"method_chain":"some_method","args":[],"kwargs":{}}'`)])],-1)])]),_:1})]),_:1})]),_:1})])}}}),E=S(X,[["__scopeId","data-v-82aa3057"]]);export{E as default};
