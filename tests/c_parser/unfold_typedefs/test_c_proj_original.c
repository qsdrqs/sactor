// From Project c_fsm, under MIT license

/* forward declaration for typedefs */
struct cfsm_Ctx;

/**
 * @brief Function pointer type for enter/leave operations.
 *
 */
typedef void (*cfsm_TransitionFunction)(struct cfsm_Ctx * fsm);

/**
 * @brief Function pointer type for event signal operation.
 *
 */
typedef void (*cfsm_EventFunction)(struct cfsm_Ctx * fsm, int eventId);

/**
 * @brief  * @brief Function pointer type for cyclic process operation.
 *
 */
typedef void (*cfsm_ProcessFunction)(struct cfsm_Ctx * fsm);

/**
 * @brief Instance data pointer as void * to accept any pointer type.
 *
 */
typedef void *cfsm_InstanceDataPtr;

/** The CFSM context data structure
*/
typedef struct cfsm_Ctx {
    cfsm_InstanceDataPtr    ctxPtr;    /**< Context instance data        */
    cfsm_TransitionFunction onLeave;   /**< Operation to run on leave    */
    cfsm_ProcessFunction    onProcess; /**< Cyclic processoperation      */
    cfsm_EventFunction      onEvent;   /**< Report event to active state */
} cfsm_Ctx;

