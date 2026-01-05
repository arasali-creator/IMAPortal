(function(){
  function poll() {
    const cnic = window.PENDING_CNIC || '';
    if(!cnic) return;
    fetch(`/approval-status/?cnic=${encodeURIComponent(cnic)}`, {credentials:'same-origin'})
      .then(r => r.json())
      .then(data => {
        if (data.approved) {
          // Once approved, send user to login so they can sign in normally:
          window.location.href = "/";
        }
      })
      .catch(()=>{ /* ignore */ })
      .finally(()=> setTimeout(poll, 5000));
  }
  setTimeout(poll, 2000);
})();
